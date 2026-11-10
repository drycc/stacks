#!/usr/bin/env bash
# tests/test_build.sh
#
# Executor tests for the "reconcile" entry of build.sh:
#   - plan inside the buildpack image, then request each planned item's tag
#   - one buildpack-dep image per run, reused for every request
#   - a failing request must not stop the remaining requests or cleanup, but
#     the run must exit non-zero
#
# Run: bash tests/test_build.sh

set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "${SCRIPT_DIR}/.." && pwd)"

passed=0
failed=0

report() {
  local name="$1" rc="$2"
  if [ "${rc}" -eq 0 ]; then
    echo "PASS: ${name}"
    passed=$((passed + 1))
  else
    echo "FAIL: ${name}"
    failed=$((failed + 1))
  fi
}

# Write a fake podman executable into <root>/bin. It records invocations
# under <root>/state (requests, builds, uploads, planner args) and serves the
# plan from <root>/plan. A build or request whose version equals
# RECONCILE_TEST_FAIL_VERSION fails.
make_fake_podman() {
  local root="$1"
  mkdir -p "${root}/bin"
  cat > "${root}/bin/podman" <<'EOF'
#!/usr/bin/env bash
set -u
echo "$*" >> "${RECONCILE_TEST_STATE}/invocations"
case " $* " in
  *" build "*)
    echo "image-build" >> "${RECONCILE_TEST_STATE}/buildpack-builds"
    if [ "${PUBLISH_TEST_IMAGE_BUILD_RC:-0}" -ne 0 ]; then
      echo "simulated buildpack image failure" >&2
      exit "${PUBLISH_TEST_IMAGE_BUILD_RC}"
    fi
    exit 0
    ;;
  *"python -m unittest discover"*)
    echo "$*" >> "${RECONCILE_TEST_STATE}/ci-tests"
    exit 0
    ;;
  *"reconcile.py abandon"*)
    echo "$*" >> "${RECONCILE_TEST_STATE}/abandons"
    if [ "${PUBLISH_TEST_ABANDON_MODE:-}" = "404" ]; then
      echo "reconcile: abandon: request ref already absent (404)"
      exit 0
    fi
    exit "${PUBLISH_TEST_ABANDON_RC:-0}"
    ;;
  *"reconcile.py request"*)
    echo "$*" >> "${RECONCILE_TEST_STATE}/requests"
    version=""
    while [ "$#" -gt 0 ]; do
      if [ "$1" = "--version" ] && [ "$#" -ge 2 ]; then
        version="$2"
        shift 2
        continue
      fi
      shift
    done
    if [ -n "${RECONCILE_TEST_FAIL_VERSION:-}" ] \
      && [ "${version}" = "${RECONCILE_TEST_FAIL_VERSION}" ]; then
      echo "simulated request failure for version ${version}" >&2
      exit "${RECONCILE_TEST_REQUEST_RC:-1}"
    fi
    exit 0
    ;;
  *"reconcile.py alert"*)
    echo "$*" >> "${RECONCILE_TEST_STATE}/alerts"
    log_file=""
    while [ "$#" -gt 0 ]; do
      if [ "$1" = "--log-file" ] && [ "$#" -ge 2 ]; then
        log_file="$2"
        shift 2
        continue
      fi
      shift
    done
    if [ -n "${log_file}" ] && [ -f "${log_file}" ]; then
      cat "${log_file}" >> "${RECONCILE_TEST_STATE}/alert-logs"
    fi
    if [ "${PUBLISH_TEST_ALERT_RC:-0}" -ne 0 ]; then
      echo "simulated alert failure" >&2
      exit "${PUBLISH_TEST_ALERT_RC}"
    fi
    exit 0
    ;;
  *"reconcile.py success"*)
    echo "$*" >> "${RECONCILE_TEST_STATE}/successes"
    if [ "${PUBLISH_TEST_SUCCESS_RC:-0}" -ne 0 ]; then
      echo "simulated resolve failure" >&2
      exit "${PUBLISH_TEST_SUCCESS_RC}"
    fi
    exit 0
    ;;
  *"retention.py"*)
    echo "$*" >> "${RECONCILE_TEST_STATE}/retentions"
    exit "${RECONCILE_TEST_RETENTION_RC:-0}"
    ;;
  *"cleaner.py"*)
    echo "$*" >> "${RECONCILE_TEST_STATE}/cleaners"
    exit "${RECONCILE_TEST_CLEANER_RC:-0}"
    ;;
  *"cleanup_obsolete_tags.py"*)
    echo "$*" >> "${RECONCILE_TEST_STATE}/tag-cleanups"
    exit "${RECONCILE_TEST_TAG_CLEANUP_RC:-0}"
    ;;
  *"reconcile.py reconcile-issues"*)
    echo "$*" >> "${RECONCILE_TEST_STATE}/issue-reconciles"
    exit "${RECONCILE_TEST_ISSUE_RC:-0}"
    ;;
  *"reconcile.py"*)
    echo "$*" >> "${RECONCILE_TEST_STATE}/plans"
    cat "${RECONCILE_TEST_PLAN}"
    exit 0
    ;;
  *"storage.py artifact-exists"*)
    echo "$*" >> "${RECONCILE_TEST_STATE}/artifact-checks"
    if [ -f "${RECONCILE_TEST_STATE}/artifact-checked" ]; then
      result="${PUBLISH_TEST_ARTIFACT_AFTER:-0}"
    else
      result="${PUBLISH_TEST_ARTIFACT_BEFORE:-1}"
      touch "${RECONCILE_TEST_STATE}/artifact-checked"
    fi
    echo "${result}" >> "${RECONCILE_TEST_STATE}/artifact-statuses"
    if [ "${result}" -eq 2 ]; then
      echo "simulated artifact verification error" >&2
    elif [ "${result}" -eq 1 ] && [ "${PUBLISH_TEST_UPLOAD_MODE:-normal}" = "symlink" ]; then
      echo "simulated symlink-only artifact" >&2
    fi
    exit "${result}"
    ;;
  *"storage.py upload"*)
    echo "$*" >> "${RECONCILE_TEST_STATE}/uploads"
    echo "simulated ${PUBLISH_TEST_UPLOAD_MODE:-normal} upload"
    if [ "${PUBLISH_TEST_UPLOAD_RC:-0}" -ne 0 ]; then
      echo "simulated upload failure" >&2
      exit "${PUBLISH_TEST_UPLOAD_RC}"
    fi
    exit 0
    ;;
  *"storage.py"*)
    echo "$*" >> "${RECONCILE_TEST_STATE}/uploads"
    exit 0
    ;;
  *" ./build.sh "*)
    stack="" version=""
    for arg in "$@"; do
      case "${arg}" in
        STACK_NAME=*) stack="${arg#STACK_NAME=}" ;;
        STACK_VERSION=*) version="${arg#STACK_VERSION=}" ;;
      esac
    done
    echo "${stack}@${version}" >> "${RECONCILE_TEST_STATE}/builds"
    if [ -n "${RECONCILE_TEST_FAIL_VERSION:-}" ] \
      && [ "${version}" = "${RECONCILE_TEST_FAIL_VERSION}" ]; then
      echo "simulated build failure for ${stack}@${version}" >&2
      exit 1
    fi
    if [ "${PUBLISH_TEST_BUILD_RC:-0}" -ne 0 ]; then
      echo "simulated build failure for ${stack}@${version}" >&2
      exit "${PUBLISH_TEST_BUILD_RC}"
    fi
    echo "built ${stack}@${version}"
    exit 0
    ;;
  *)
    echo "fake podman: unexpected invocation: $*" >&2
    exit 1
    ;;
esac
EOF
  chmod +x "${root}/bin/podman"
}

# Run build.sh's reconcile inside an isolated subshell with the fake podman
# on PATH. Returns "rc|builds|uploads|image_builds|root". Arguments after
# dry_run are forwarded to reconcile (e.g. --arch arm64 --max-total 5).
run_reconcile() {
  local root="$1" plan_content="$2" fail_version="${3:-}" dry_run="${4:-}"
  shift 4
  mkdir -p "${root}/state"
  printf '%s' "${plan_content}" > "${root}/plan"
  make_fake_podman "${root}"
  if [ "${RECONCILE_TEST_MKTEMP_FAIL:-0}" = "1" ]; then
    cat > "${root}/bin/mktemp" <<'EOF'
#!/usr/bin/env bash
echo "simulated mktemp failure" >&2
exit 1
EOF
    chmod +x "${root}/bin/mktemp"
  fi
  local rc=0
  (
    export CODENAME=debian-13
    export DRYCC_REGISTRY=registry.drycc.cc
    export OSS_ENDPOINT=http://fake-oss
    export OSS_ACCESS_KEY_ID=fake-id
    export OSS_ACCESS_KEY_SECRET=fake-secret
    # an empty GITHUB_TOKEN stays empty (the no-token test relies on that);
    # unset falls back to the fake token
    export GITHUB_TOKEN="${GITHUB_TOKEN-fake-token}"
    export CI_COMMIT_SHA="${CI_COMMIT_SHA:-1111111111111111111111111111111111111111}"
    export RECONCILE_TEST_STATE="${root}/state"
    export RECONCILE_TEST_PLAN="${root}/plan"
    export RECONCILE_TEST_FAIL_VERSION="${fail_version}"
    export RECONCILE_TEST_REQUEST_RC="${RECONCILE_TEST_REQUEST_RC:-1}"
    export RECONCILE_DRY_RUN="${dry_run}"
    export CLEANER_DRY_RUN="${CLEANER_DRY_RUN:-}"
    export CLEANER_KEEP_COUNT="${CLEANER_KEEP_COUNT:-2}"
    export RECONCILE_TEST_CLEANER_RC="${RECONCILE_TEST_CLEANER_RC:-0}"
    export RECONCILE_TEST_TAG_CLEANUP_RC="${RECONCILE_TEST_TAG_CLEANUP_RC:-0}"
    export RECONCILE_TEST_ISSUE_RC="${RECONCILE_TEST_ISSUE_RC:-0}"
    export RECONCILE_TEST_RETENTION_RC="${RECONCILE_TEST_RETENTION_RC:-0}"
    export PATH="${root}/bin:${PATH}"
    # shellcheck source=/dev/null
    . "${REPO}/build.sh"
    reconcile "$@"
  ) > "${root}/out.log" 2>&1
  rc=$?
  local builds uploads image_builds
  builds="$(cat "${root}/state/builds" 2> /dev/null | paste -sd, -)"
  uploads="$(grep -c . "${root}/state/uploads" 2> /dev/null || echo 0)"
  image_builds="$(grep -c . "${root}/state/buildpack-builds" 2> /dev/null || echo 0)"
  echo "${rc}|${builds}|${uploads}|${image_builds}|${root}"
}

count_calls() {
  # count_calls <file> <pattern>: number of recorded invocations matching
  local count
  count="$(grep -c -- "${2}" "${1}" 2> /dev/null || true)"
  echo "${count:-0}"
}

parse_result() {
  IFS='|' read -r RESULT_RC RESULT_BUILDS RESULT_UPLOADS RESULT_IMAGE_BUILDS RESULT_ROOT <<< "$1"
}

# Run the tag publisher with the same fake podman boundary as reconcile.
# PUBLISH_TEST_ARTIFACT_BEFORE/AFTER are storage.py artifact-exists statuses
# (0 normal object, 1 missing/symlink, 2 verification error).
run_publish() {
  local root="$1" tag="$2" rc=0
  mkdir -p "${root}/state"
  make_fake_podman "${root}"
  (
    export CODENAME=debian-13
    export DRYCC_REGISTRY=registry.drycc.cc
    export OSS_ENDPOINT=http://fake-oss
    export OSS_ACCESS_KEY_ID=fake-id
    export OSS_ACCESS_KEY_SECRET=fake-secret
    export GITHUB_TOKEN=fake-token
    export CI_COMMIT_SHA=1111111111111111111111111111111111111111
    export CI_COMMIT_TAG="${CI_COMMIT_TAG:-nginx@1.31.8}"
    export RECONCILE_TEST_STATE="${root}/state"
    export RECONCILE_TEST_FAIL_VERSION=""
    export PUBLISH_TEST_ARTIFACT_BEFORE="${PUBLISH_TEST_ARTIFACT_BEFORE:-1}"
    export PUBLISH_TEST_ARTIFACT_AFTER="${PUBLISH_TEST_ARTIFACT_AFTER:-0}"
    export PUBLISH_TEST_IMAGE_BUILD_RC="${PUBLISH_TEST_IMAGE_BUILD_RC:-0}"
    export PUBLISH_TEST_BUILD_RC="${PUBLISH_TEST_BUILD_RC:-0}"
    export PUBLISH_TEST_UPLOAD_RC="${PUBLISH_TEST_UPLOAD_RC:-0}"
    export PUBLISH_TEST_UPLOAD_MODE="${PUBLISH_TEST_UPLOAD_MODE:-normal}"
    export PUBLISH_TEST_ALERT_RC="${PUBLISH_TEST_ALERT_RC:-0}"
    export PUBLISH_TEST_SUCCESS_RC="${PUBLISH_TEST_SUCCESS_RC:-0}"
    export PUBLISH_TEST_ABANDON_RC="${PUBLISH_TEST_ABANDON_RC:-0}"
    export PUBLISH_TEST_ABANDON_MODE="${PUBLISH_TEST_ABANDON_MODE:-}"
    export PATH="${root}/bin:${PATH}"
    if [ "${tag}" = "__DEFAULT__" ]; then
      bash "${REPO}/build.sh" publish
    else
      bash "${REPO}/build.sh" publish "${tag}"
    fi
  ) > "${root}/out.log" 2>&1 || rc=$?
  echo "${rc}|${root}"
}

parse_publish_result() {
  IFS='|' read -r RESULT_RC RESULT_ROOT <<< "$1"
}

report_publish_result() {
  local name="$1" root="$2" problems="$3"
  if [ -z "${problems}" ]; then
    report "${name}" 0
    rm -rf "${root}"
  else
    RESULT_ROOT="${root}"
    show_log_on_failure "${problems}" || true
    report "${name}" 1
  fi
}

show_log_on_failure() {
  local problems="$1"
  echo "  reconcile:${problems}" >&2
  sed 's/^/    /' "${RESULT_ROOT}/out.log" >&2
  rm -rf "${RESULT_ROOT}"
  return 1
}

test_reconcile_requests_each_planned_item_without_building() {
  local out problems=""
  # GITHUB_TOKEN is pinned to the fake token the assertions below expect;
  # run_reconcile forwards an inherited token, so isolate from the parent env.
  out="$(GITHUB_TOKEN=fake-token run_reconcile "$(mktemp -d)" $'nginx@1.31.8\nrustfs@1.0.4\nredis@8.2.1\n' '' '')"
  parse_result "${out}"
  [ "${RESULT_RC}" -eq 0 ] || problems="${problems} exit=${RESULT_RC}"
  [ "${RESULT_IMAGE_BUILDS}" -eq 1 ] || problems="${problems} image_builds=${RESULT_IMAGE_BUILDS}"
  [ -z "${RESULT_BUILDS}" ] || problems="${problems} unexpected-builds=[${RESULT_BUILDS}]"
  [ "${RESULT_UPLOADS}" -eq 0 ] || problems="${problems} unexpected-uploads=${RESULT_UPLOADS}"
  [ "$(count_calls "${RESULT_ROOT}/state/requests" "reconcile.py request")" -eq 3 ] \
    || problems="${problems} requests=$(count_calls "${RESULT_ROOT}/state/requests" "reconcile.py request")"
  grep -q -- "--stack nginx --version 1.31.8 --sha 1111111111111111111111111111111111111111" \
    "${RESULT_ROOT}/state/requests" 2> /dev/null || problems="${problems} nginx-request-or-sha-missing"
  grep -q -- "--stack rustfs --version 1.0.4 --sha 1111111111111111111111111111111111111111" \
    "${RESULT_ROOT}/state/requests" 2> /dev/null || problems="${problems} rustfs-request-or-sha-missing"
  grep -q -- "--stack redis --version 8.2.1 --sha 1111111111111111111111111111111111111111" \
    "${RESULT_ROOT}/state/requests" 2> /dev/null || problems="${problems} redis-request-or-sha-missing"
  grep -q "requested=3 failed=0" "${RESULT_ROOT}/out.log" || problems="${problems} summary-missing"
  [ "$(count_calls "${RESULT_ROOT}/state/successes" "reconcile.py success")" -eq 0 ] \
    || problems="${problems} unexpected-success-report"
  [ "$(count_calls "${RESULT_ROOT}/state/alerts" "reconcile.py alert")" -eq 0 ] \
    || problems="${problems} unexpected-alert"
  [ "$(count_calls "${RESULT_ROOT}/state/retentions" "retention.py")" -eq 1 ] \
    || problems="${problems} retention-generator-not-called"
  grep -q -- "--repos retention-repo.txt --static retention-list.txt --output" \
    "${RESULT_ROOT}/state/retentions" 2> /dev/null || problems="${problems} retention-args-missing"
  [ "$(count_calls "${RESULT_ROOT}/state/cleaners" "cleaner.py")" -eq 1 ] \
    || problems="${problems} cleaner-not-called"
  grep -q -- "oss-stacks -n 2 --arch auto --confirm" "${RESULT_ROOT}/state/cleaners" 2> /dev/null \
    || problems="${problems} cleaner-args-missing"
  grep -q -- "--retention-list .*retention-list.generated.txt" "${RESULT_ROOT}/state/cleaners" 2> /dev/null \
    || problems="${problems} generated-list-not-passed-to-cleaner"
  [ "$(count_calls "${RESULT_ROOT}/state/tag-cleanups" "cleanup_obsolete_tags.py")" -eq 1 ] \
    || problems="${problems} obsolete-tag-cleaner-not-called"
  grep -q -- "--env GITHUB_TOKEN=fake-token" "${RESULT_ROOT}/state/tag-cleanups" 2> /dev/null \
    || problems="${problems} github-token-not-forwarded"
  grep -q -- "python3 scripts/cleanup_obsolete_tags.py --confirm$" \
    "${RESULT_ROOT}/state/tag-cleanups" 2> /dev/null \
    || problems="${problems} obsolete-tag-confirm-missing"
  local cleaner_line tag_cleanup_line
  cleaner_line="$(grep -n 'cleaner.py' "${RESULT_ROOT}/state/invocations" | cut -d: -f1)"
  tag_cleanup_line="$(grep -n 'cleanup_obsolete_tags.py' "${RESULT_ROOT}/state/invocations" | cut -d: -f1)"
  [ -n "${cleaner_line}" ] && [ -n "${tag_cleanup_line}" ] \
    && [ "${cleaner_line}" -lt "${tag_cleanup_line}" ] \
    || problems="${problems} obsolete-tag-cleaner-order"
  if [ -z "${problems}" ]; then
    report "reconcile requests each planned item without building" 0
    rm -rf "${RESULT_ROOT}"
  else
    show_log_on_failure "${problems}" || true
    report "reconcile requests each planned item without building" 1
  fi
}

test_reconcile_request_failure_continues_and_cleans_before_exiting_non_zero() {
  local out problems=""
  out="$(run_reconcile "$(mktemp -d)" $'nginx@1.31.8\nbadstack@9.9.9\nrustfs@1.0.4\n' '9.9.9' '')"
  parse_result "${out}"
  [ "${RESULT_RC}" -ne 0 ] || problems="${problems} exit=0"
  [ "${RESULT_IMAGE_BUILDS}" -eq 1 ] || problems="${problems} image_builds=${RESULT_IMAGE_BUILDS}"
  [ -z "${RESULT_BUILDS}" ] || problems="${problems} unexpected-builds=[${RESULT_BUILDS}]"
  [ "${RESULT_UPLOADS}" -eq 0 ] || problems="${problems} unexpected-uploads=${RESULT_UPLOADS}"
  [ "$(count_calls "${RESULT_ROOT}/state/requests" "reconcile.py request")" -eq 3 ] \
    || problems="${problems} requests=$(count_calls "${RESULT_ROOT}/state/requests" "reconcile.py request")"
  grep -q -- "--stack badstack --version 9.9.9" "${RESULT_ROOT}/state/requests" 2> /dev/null \
    || problems="${problems} failed-request-missing"
  grep -q -- "--stack rustfs --version 1.0.4" "${RESULT_ROOT}/state/requests" 2> /dev/null \
    || problems="${problems} later-request-missing"
  grep -q "requested=2 failed=1" "${RESULT_ROOT}/out.log" || problems="${problems} summary-missing"
  grep -q '^reconcile: failed (1):$' "${RESULT_ROOT}/out.log" || problems="${problems} failed-list-missing"
  grep -q '^  badstack@9.9.9$' "${RESULT_ROOT}/out.log" || problems="${problems} failed-badstack-missing"
  grep -q '^reconcile: run failed: 1 request failure(s), cleanup=ok$' "${RESULT_ROOT}/out.log" \
    || problems="${problems} final-failure-missing"
  [ "$(count_calls "${RESULT_ROOT}/state/alerts" "reconcile.py alert")" -eq 0 ] \
    || problems="${problems} unexpected-alert"
  [ "$(count_calls "${RESULT_ROOT}/state/successes" "reconcile.py success")" -eq 0 ] \
    || problems="${problems} unexpected-success-report"
  [ "$(count_calls "${RESULT_ROOT}/state/retentions" "retention.py")" -eq 1 ] \
    || problems="${problems} retention-not-called-after-failure"
  [ "$(count_calls "${RESULT_ROOT}/state/cleaners" "cleaner.py")" -eq 1 ] \
    || problems="${problems} cleaner-not-called-after-failure"
  if [ -z "${problems}" ]; then
    report "reconcile request failure continues and cleans before exiting non-zero" 0
    rm -rf "${RESULT_ROOT}"
  else
    show_log_on_failure "${problems}" || true
    report "reconcile request failure continues and cleans before exiting non-zero" 1
  fi
}

test_reconcile_request_returns_the_underlying_command_status() {
  local root rc=0 problems=""
  root="$(mktemp -d)"
  mkdir -p "${root}/state"
  make_fake_podman "${root}"
  RESULT_ROOT="${root}"
  (
    export CODENAME=debian-13
    export DRYCC_REGISTRY=registry.drycc.cc
    export GITHUB_TOKEN=fake-token
    export CI_COMMIT_SHA=1111111111111111111111111111111111111111
    export RECONCILE_TEST_STATE="${root}/state"
    export RECONCILE_TEST_FAIL_VERSION=9.9.9
    export RECONCILE_TEST_REQUEST_RC=23
    export PATH="${root}/bin:${PATH}"
    # shellcheck source=/dev/null
    . "${REPO}/build.sh"
    reconcile-request badstack 9.9.9
  ) > "${root}/out.log" 2>&1 || rc=$?
  [ "${rc}" -eq 23 ] || problems="${problems} exit=${rc}"
  [ "$(count_calls "${root}/state/requests" "reconcile.py request")" -eq 1 ] \
    || problems="${problems} request-not-called"
  if [ -z "${problems}" ]; then
    report "reconcile-request returns the underlying command status" 0
    rm -rf "${root}"
  else
    show_log_on_failure "${problems}" || true
    report "reconcile-request returns the underlying command status" 1
  fi
}

test_reconcile_with_empty_plan_requests_nothing() {
  local out problems=""
  out="$(run_reconcile "$(mktemp -d)" '' '' '')"
  parse_result "${out}"
  [ "${RESULT_RC}" -eq 0 ] || problems="${problems} exit=${RESULT_RC}"
  [ -z "${RESULT_BUILDS}" ] || problems="${problems} builds=[${RESULT_BUILDS}]"
  [ "${RESULT_UPLOADS}" -eq 0 ] || problems="${problems} uploads=${RESULT_UPLOADS}"
  [ "${RESULT_IMAGE_BUILDS}" -eq 1 ] || problems="${problems} image_builds=${RESULT_IMAGE_BUILDS}"
  [ "$(count_calls "${RESULT_ROOT}/state/requests" "reconcile.py request")" -eq 0 ] \
    || problems="${problems} unexpected-request"
  grep -q "nothing to build" "${RESULT_ROOT}/out.log" || problems="${problems} message-missing"
  [ "$(count_calls "${RESULT_ROOT}/state/cleaners" "cleaner.py")" -eq 1 ] \
    || problems="${problems} empty-plan-cleaner-not-called"
  if [ -z "${problems}" ]; then
    report "reconcile with empty plan requests nothing" 0
    rm -rf "${RESULT_ROOT}"
  else
    show_log_on_failure "${problems}" || true
    report "reconcile with empty plan requests nothing" 1
  fi
}

test_reconcile_dry_run_prints_the_plan_without_requesting() {
  local out problems=""
  out="$(run_reconcile "$(mktemp -d)" $'nginx@1.31.8\nrustfs@1.0.4\n' '' '1')"
  parse_result "${out}"
  [ "${RESULT_RC}" -eq 0 ] || problems="${problems} exit=${RESULT_RC}"
  [ -z "${RESULT_BUILDS}" ] || problems="${problems} builds=[${RESULT_BUILDS}]"
  [ "${RESULT_UPLOADS}" -eq 0 ] || problems="${problems} uploads=${RESULT_UPLOADS}"
  [ "${RESULT_IMAGE_BUILDS}" -eq 1 ] || problems="${problems} image_builds=${RESULT_IMAGE_BUILDS}"
  [ "$(count_calls "${RESULT_ROOT}/state/requests" "reconcile.py request")" -eq 0 ] \
    || problems="${problems} unexpected-request"
  grep -q "dry run" "${RESULT_ROOT}/out.log" || problems="${problems} dry-run-message-missing"
  grep -q "nginx@1.31.8" "${RESULT_ROOT}/out.log" || problems="${problems} plan-items-missing"
  grep -q "rustfs@1.0.4" "${RESULT_ROOT}/out.log" || problems="${problems} plan-items-missing"
  grep -q "reconcile: building" "${RESULT_ROOT}/out.log" && problems="${problems} unexpected-build-attempt"
  grep -q "reconcile: requesting" "${RESULT_ROOT}/out.log" && problems="${problems} unexpected-request-attempt"
  [ "$(count_calls "${RESULT_ROOT}/state/cleaners" "cleaner.py")" -eq 1 ] \
    || problems="${problems} dry-run-cleaner-not-called"
  grep -q -- "oss-stacks -n 2 --arch auto --dry-run" "${RESULT_ROOT}/state/cleaners" 2> /dev/null \
    || problems="${problems} cleaner-dry-run-args-missing"
  [ "$(count_calls "${RESULT_ROOT}/state/tag-cleanups" "cleanup_obsolete_tags.py")" -eq 1 ] \
    || problems="${problems} dry-run-obsolete-tag-cleaner-not-called"
  grep -q -- "python3 scripts/cleanup_obsolete_tags.py$" \
    "${RESULT_ROOT}/state/tag-cleanups" 2> /dev/null \
    || problems="${problems} reconcile-dry-run-passed-confirm-to-tag-cleaner"
  if [ -z "${problems}" ]; then
    report "reconcile dry run prints the plan without requesting" 0
    rm -rf "${RESULT_ROOT}"
  else
    show_log_on_failure "${problems}" || true
    report "reconcile dry run prints the plan without requesting" 1
  fi
}

test_reconcile_forwards_planner_arguments() {
  local out problems=""
  out="$(run_reconcile "$(mktemp -d)" $'nginx@1.31.8\n' '' '' --arch arm64 --max-total 5)"
  parse_result "${out}"
  [ "${RESULT_RC}" -eq 0 ] || problems="${problems} exit=${RESULT_RC}"
  grep -q "reconcile.py plan --arch arm64 --max-total 5" \
    "${RESULT_ROOT}/state/plans" 2> /dev/null \
    || problems="${problems} planner-args-not-forwarded=[ $(cat "${RESULT_ROOT}/state/plans" 2> /dev/null) ]"
  if [ -z "${problems}" ]; then
    report "reconcile forwards planner arguments" 0
    rm -rf "${RESULT_ROOT}"
  else
    show_log_on_failure "${problems}" || true
    report "reconcile forwards planner arguments" 1
  fi
}

test_retention_generation_failure_skips_cleaner() {
  local out problems=""
  out="$(RECONCILE_TEST_RETENTION_RC=1 run_reconcile "$(mktemp -d)" $'nginx@1.31.8\n' '' '')"
  parse_result "${out}"
  [ "${RESULT_RC}" -ne 0 ] || problems="${problems} exit=0"
  [ "$(count_calls "${RESULT_ROOT}/state/retentions" "retention.py")" -eq 1 ] \
    || problems="${problems} retention-generator-not-called"
  [ "$(count_calls "${RESULT_ROOT}/state/cleaners" "cleaner.py")" -eq 0 ] \
    || problems="${problems} cleaner-ran-after-retention-failure"
  grep -q "retention generation failed" "${RESULT_ROOT}/out.log" \
    || problems="${problems} retention-error-missing"
  grep -q '^reconcile: run failed: 0 request failure(s), cleanup=failed$' "${RESULT_ROOT}/out.log" \
    || problems="${problems} final-retention-failure-missing"
  if [ -z "${problems}" ]; then
    report "retention generation failure skips cleaner" 0
    rm -rf "${RESULT_ROOT}"
  else
    show_log_on_failure "${problems}" || true
    report "retention generation failure skips cleaner" 1
  fi
}

test_reconcile_cleaner_failure_fails_the_run() {
  local out problems=""
  out="$(RECONCILE_TEST_CLEANER_RC=1 run_reconcile "$(mktemp -d)" $'nginx@1.31.8\n' '' '')"
  parse_result "${out}"
  [ "${RESULT_RC}" -ne 0 ] || problems="${problems} exit=0"
  [ -z "${RESULT_BUILDS}" ] || problems="${problems} unexpected-builds=[${RESULT_BUILDS}]"
  [ "$(count_calls "${RESULT_ROOT}/state/requests" "reconcile.py request")" -eq 1 ] \
    || problems="${problems} request-not-called"
  [ "$(count_calls "${RESULT_ROOT}/state/cleaners" "cleaner.py")" -eq 1 ] \
    || problems="${problems} cleaner-not-called"
  [ "$(count_calls "${RESULT_ROOT}/state/tag-cleanups" "cleanup_obsolete_tags.py")" -eq 0 ] \
    || problems="${problems} tag-cleaner-ran-after-oss-failure"
  grep -q "cleanup failed" "${RESULT_ROOT}/out.log" || problems="${problems} cleanup-error-missing"
  grep -q '^reconcile: run failed: 0 request failure(s), cleanup=failed$' "${RESULT_ROOT}/out.log" \
    || problems="${problems} final-cleanup-failure-missing"
  if [ -z "${problems}" ]; then
    report "reconcile cleaner failure fails the run" 0
    rm -rf "${RESULT_ROOT}"
  else
    show_log_on_failure "${problems}" || true
    report "reconcile cleaner failure fails the run" 1
  fi
}

test_cleaner_dry_run_also_disables_obsolete_tag_deletion() {
  local out problems=""
  out="$(CLEANER_DRY_RUN=1 run_reconcile "$(mktemp -d)" $'nginx@1.31.8\n' '' '')"
  parse_result "${out}"
  [ "${RESULT_RC}" -eq 0 ] || problems="${problems} exit=${RESULT_RC}"
  grep -q -- "oss-stacks -n 2 --arch auto --dry-run" "${RESULT_ROOT}/state/cleaners" 2> /dev/null \
    || problems="${problems} cleaner-dry-run-args-missing"
  [ "$(count_calls "${RESULT_ROOT}/state/tag-cleanups" "cleanup_obsolete_tags.py")" -eq 1 ] \
    || problems="${problems} obsolete-tag-cleaner-not-called"
  grep -q -- "python3 scripts/cleanup_obsolete_tags.py$" \
    "${RESULT_ROOT}/state/tag-cleanups" 2> /dev/null \
    || problems="${problems} cleaner-dry-run-passed-confirm-to-tag-cleaner"
  if [ -z "${problems}" ]; then
    report "cleaner dry run also disables obsolete tag deletion" 0
    rm -rf "${RESULT_ROOT}"
  else
    show_log_on_failure "${problems}" || true
    report "cleaner dry run also disables obsolete tag deletion" 1
  fi
}


test_reconcile_obsolete_tag_cleanup_failure_fails_the_run() {
  local out problems=""
  out="$(RECONCILE_TEST_TAG_CLEANUP_RC=19 run_reconcile "$(mktemp -d)" $'nginx@1.31.8\n' '' '')"
  parse_result "${out}"
  [ "${RESULT_RC}" -ne 0 ] || problems="${problems} exit=0"
  [ "$(count_calls "${RESULT_ROOT}/state/cleaners" "cleaner.py")" -eq 1 ] \
    || problems="${problems} cleaner-not-called"
  [ "$(count_calls "${RESULT_ROOT}/state/tag-cleanups" "cleanup_obsolete_tags.py")" -eq 1 ] \
    || problems="${problems} obsolete-tag-cleaner-not-called"
  grep -q "obsolete tag cleanup failed" "${RESULT_ROOT}/out.log" \
    || problems="${problems} obsolete-tag-cleanup-error-missing"
  grep -q '^reconcile: run failed: 0 request failure(s), cleanup=failed$' "${RESULT_ROOT}/out.log" \
    || problems="${problems} final-obsolete-tag-cleanup-failure-missing"
  if [ -z "${problems}" ]; then
    report "reconcile obsolete tag cleanup failure fails the run" 0
    rm -rf "${RESULT_ROOT}"
  else
    show_log_on_failure "${problems}" || true
    report "reconcile obsolete tag cleanup failure fails the run" 1
  fi
}


test_reconcile_clean_reconciles_issues_after_tag_cleanup() {
  local out problems=""
  out="$(run_reconcile "$(mktemp -d)" $'nginx@1.31.8\n' '' '')"
  parse_result "${out}"
  [ "${RESULT_RC}" -eq 0 ] || problems="${problems} exit=${RESULT_RC}"
  [ "$(count_calls "${RESULT_ROOT}/state/issue-reconciles" "reconcile.py reconcile-issues")" -eq 1 ] \
    || problems="${problems} issue-reconciler-not-called"
  grep -q -- "python3 scripts/reconcile.py reconcile-issues --arch auto$" \
    "${RESULT_ROOT}/state/issue-reconciles" 2> /dev/null \
    || problems="${problems} issue-reconciler-args-missing=[ $(cat "${RESULT_ROOT}/state/issue-reconciles" 2> /dev/null) ]"
  local tag_cleanup_line issue_line
  tag_cleanup_line="$(grep -n 'cleanup_obsolete_tags.py' "${RESULT_ROOT}/state/invocations" | cut -d: -f1)"
  issue_line="$(grep -n 'reconcile.py reconcile-issues' "${RESULT_ROOT}/state/invocations" | cut -d: -f1)"
  [ -n "${tag_cleanup_line}" ] && [ -n "${issue_line}" ] \
    && [ "${tag_cleanup_line}" -lt "${issue_line}" ] \
    || problems="${problems} issue-reconciler-order"
  if [ -z "${problems}" ]; then
    report "reconcile-clean reconciles issues after tag cleanup" 0
    rm -rf "${RESULT_ROOT}"
  else
    show_log_on_failure "${problems}" || true
    report "reconcile-clean reconciles issues after tag cleanup" 1
  fi
}


test_reconcile_clean_forwards_dry_run_to_issue_reconciliation() {
  local out problems=""
  for mode in reconcile_dry_run cleaner_dry_run; do
    problems=""
    case "${mode}" in
      reconcile_dry_run) out="$(run_reconcile "$(mktemp -d)" $'nginx@1.31.8\n' '' '1')" ;;
      cleaner_dry_run)   out="$(CLEANER_DRY_RUN=1 run_reconcile "$(mktemp -d)" $'nginx@1.31.8\n' '' '')" ;;
    esac
    parse_result "${out}"
    [ "${RESULT_RC}" -eq 0 ] || problems="${problems} ${mode}: exit=${RESULT_RC}"
    [ "$(count_calls "${RESULT_ROOT}/state/issue-reconciles" "reconcile.py reconcile-issues")" -eq 1 ] \
      || problems="${problems} ${mode}: issue-reconciler-not-called"
    grep -q -- "python3 scripts/reconcile.py reconcile-issues --arch auto --dry-run$" \
      "${RESULT_ROOT}/state/issue-reconciles" 2> /dev/null \
      || problems="${problems} ${mode}: dry-run-flag-missing=[ $(cat "${RESULT_ROOT}/state/issue-reconciles" 2> /dev/null) ]"
    if [ -n "${problems}" ]; then
      show_log_on_failure "${problems}" || true
      report "reconcile-clean forwards dry run to issue reconciliation (${mode})" 1
      return
    fi
    rm -rf "${RESULT_ROOT}"
  done
  report "reconcile-clean forwards dry run to issue reconciliation" 0
}


test_reconcile_issue_reconciliation_failure_fails_the_run() {
  local out problems=""
  out="$(RECONCILE_TEST_ISSUE_RC=23 run_reconcile "$(mktemp -d)" $'nginx@1.31.8\n' '' '')"
  parse_result "${out}"
  [ "${RESULT_RC}" -ne 0 ] || problems="${problems} exit=0"
  [ "$(count_calls "${RESULT_ROOT}/state/cleaners" "cleaner.py")" -eq 1 ] \
    || problems="${problems} cleaner-not-called"
  [ "$(count_calls "${RESULT_ROOT}/state/tag-cleanups" "cleanup_obsolete_tags.py")" -eq 1 ] \
    || problems="${problems} obsolete-tag-cleaner-not-called"
  [ "$(count_calls "${RESULT_ROOT}/state/issue-reconciles" "reconcile.py reconcile-issues")" -eq 1 ] \
    || problems="${problems} issue-reconciler-not-called"
  grep -q "issue reconciliation failed" "${RESULT_ROOT}/out.log" \
    || problems="${problems} issue-reconciliation-error-missing"
  grep -q '^reconcile: run failed: 0 request failure(s), cleanup=failed$' "${RESULT_ROOT}/out.log" \
    || problems="${problems} final-issue-reconciliation-failure-missing"
  if [ -z "${problems}" ]; then
    report "reconcile issue reconciliation failure fails the run" 0
    rm -rf "${RESULT_ROOT}"
  else
    show_log_on_failure "${problems}" || true
    report "reconcile issue reconciliation failure fails the run" 1
  fi
}


test_ci_test_uses_buildpack_image() {
  local root rc=0 problems=""
  root="$(mktemp -d)"
  mkdir -p "${root}/state"
  make_fake_podman "${root}"
  RESULT_ROOT="${root}"
  (
    export CODENAME=debian-13
    export DRYCC_REGISTRY=registry.drycc.cc
    export RECONCILE_TEST_STATE="${root}/state"
    export PATH="${root}/bin:${PATH}"
    bash "${REPO}/build.sh" test
  ) > "${root}/out.log" 2>&1 || rc=$?
  [ "${rc}" -eq 0 ] || problems="${problems} exit=${rc}"
  [ "$(count_calls "${root}/state/buildpack-builds" "image-build")" -eq 1 ] \
    || problems="${problems} buildpack-image-not-built"
  [ "$(count_calls "${root}/state/ci-tests" "python -m unittest discover")" -eq 1 ] \
    || problems="${problems} test-container-not-called"
  grep -q "buildpack-dep:debian-13" "${root}/state/ci-tests" 2> /dev/null \
    || problems="${problems} buildpack-image-not-used"
  grep -q "for test_script in tests/test_\*.sh" "${root}/state/ci-tests" 2> /dev/null \
    || problems="${problems} shell-tests-missing"
  if grep -q "pip install" "${root}/state/ci-tests" 2> /dev/null; then
    problems="${problems} unexpected-pip-install"
  fi
  if [ -z "${problems}" ]; then
    report "build.sh test uses buildpack image for all tests" 0
    rm -rf "${root}"
  else
    show_log_on_failure "${problems}" || true
    report "build.sh test uses buildpack image for all tests" 1
  fi
}

test_run_logged_appends_and_returns_the_command_status() {
  local root rc problems=""
  root="$(mktemp -d)"
  printf 'existing-entry\n' > "${root}/command.log"
  (
    export CODENAME=debian-13
    # shellcheck source=/dev/null
    . "${REPO}/build.sh"
    if run_logged "${root}/command.log" bash -c \
      'echo stdout-entry; echo stderr-entry >&2; exit 37'; then
      rc=0
    else
      rc=$?
    fi
    printf '%s\n' "${rc}" > "${root}/status"
  ) > "${root}/out.log" 2>&1
  [ "$(cat "${root}/status")" -eq 37 ] || problems="${problems} command-status-not-preserved"
  grep -q '^stdout-entry$' "${root}/out.log" || problems="${problems} stdout-not-streamed"
  grep -q '^stderr-entry$' "${root}/out.log" || problems="${problems} stderr-not-streamed"
  grep -q '^existing-entry$' "${root}/command.log" || problems="${problems} existing-log-overwritten"
  grep -q '^stdout-entry$' "${root}/command.log" || problems="${problems} stdout-not-logged"
  grep -q '^stderr-entry$' "${root}/command.log" || problems="${problems} stderr-not-logged"
  report_publish_result "run_logged appends and returns the command status" "${root}" "${problems}"
}

test_publish_existing_artifact_skips_build_and_resolves() {
  local out problems=""
  out="$(PUBLISH_TEST_ARTIFACT_BEFORE=0 run_publish "$(mktemp -d)" 'nginx@1.31.8')"
  parse_publish_result "${out}"
  [ "${RESULT_RC}" -eq 0 ] || problems="${problems} exit=${RESULT_RC}"
  [ ! -s "${RESULT_ROOT}/state/builds" ] || problems="${problems} unexpected-build"
  [ ! -s "${RESULT_ROOT}/state/uploads" ] || problems="${problems} unexpected-upload"
  [ "$(count_calls "${RESULT_ROOT}/state/artifact-checks" 'storage.py artifact-exists')" -eq 1 ] \
    || problems="${problems} preflight-count"
  [ "$(count_calls "${RESULT_ROOT}/state/successes" 'reconcile.py success')" -eq 1 ] \
    || problems="${problems} resolve-not-called"
  grep -q -- '--stack nginx --version 1.31.8' "${RESULT_ROOT}/state/successes" 2> /dev/null \
    || problems="${problems} wrong-resolve-item"
  [ ! -s "${RESULT_ROOT}/state/abandons" ] || problems="${problems} tag-abandoned-on-success"
  [ ! -s "${RESULT_ROOT}/state/alerts" ] || problems="${problems} unexpected-alert"
  [ ! -s "${RESULT_ROOT}/state/requests" ] || problems="${problems} unexpected-request"
  report_publish_result "publish existing artifact skips build and resolves" "${RESULT_ROOT}" "${problems}"
}

test_publish_defaults_to_ci_tag_and_builds_missing_artifact() {
  local out problems=""
  out="$(CI_COMMIT_TAG='nginx@1.31.8' PUBLISH_TEST_ARTIFACT_BEFORE=1 \
    PUBLISH_TEST_ARTIFACT_AFTER=0 run_publish "$(mktemp -d)" '__DEFAULT__')"
  parse_publish_result "${out}"
  [ "${RESULT_RC}" -eq 0 ] || problems="${problems} exit=${RESULT_RC}"
  [ "$(cat "${RESULT_ROOT}/state/builds" 2> /dev/null)" = 'nginx@1.31.8' ] \
    || problems="${problems} build-not-run-for-ci-tag"
  [ "$(count_calls "${RESULT_ROOT}/state/uploads" 'storage.py upload')" -eq 1 ] \
    || problems="${problems} upload-count"
  [ "$(count_calls "${RESULT_ROOT}/state/artifact-checks" 'storage.py artifact-exists')" -eq 2 ] \
    || problems="${problems} verification-count"
  [ "$(count_calls "${RESULT_ROOT}/state/successes" 'reconcile.py success')" -eq 1 ] \
    || problems="${problems} resolve-not-called"
  [ ! -s "${RESULT_ROOT}/state/abandons" ] || problems="${problems} tag-abandoned-on-success"
  [ ! -s "${RESULT_ROOT}/state/requests" ] || problems="${problems} unexpected-request"
  report_publish_result "publish defaults to CI tag and builds missing artifact" "${RESULT_ROOT}" "${problems}"
}

test_publish_noop_upload_fails_alerts_and_abandons() {
  local out problems=""
  out="$(PUBLISH_TEST_ARTIFACT_BEFORE=1 PUBLISH_TEST_ARTIFACT_AFTER=1 \
    PUBLISH_TEST_UPLOAD_MODE=noop run_publish "$(mktemp -d)" 'nginx@1.31.8')"
  parse_publish_result "${out}"
  [ "${RESULT_RC}" -eq 1 ] || problems="${problems} exit=${RESULT_RC}"
  [ "$(count_calls "${RESULT_ROOT}/state/artifact-checks" 'storage.py artifact-exists')" -eq 2 ] \
    || problems="${problems} verification-count"
  [ "$(count_calls "${RESULT_ROOT}/state/alerts" 'reconcile.py alert')" -eq 1 ] \
    || problems="${problems} alert-not-called"
  grep -q 'simulated noop upload' "${RESULT_ROOT}/state/alert-logs" 2> /dev/null \
    || problems="${problems} upload-log-not-passed-to-alert"
  [ "$(count_calls "${RESULT_ROOT}/state/abandons" 'reconcile.py abandon')" -eq 1 ] \
    || problems="${problems} abandon-not-called"
  [ ! -s "${RESULT_ROOT}/state/successes" ] || problems="${problems} unexpected-resolve"
  report_publish_result "publish no-op upload fails alerts and abandons" "${RESULT_ROOT}" "${problems}"
}

test_publish_symlink_only_result_fails_verification() {
  local out problems=""
  out="$(PUBLISH_TEST_ARTIFACT_BEFORE=1 PUBLISH_TEST_ARTIFACT_AFTER=1 \
    PUBLISH_TEST_UPLOAD_MODE=symlink run_publish "$(mktemp -d)" 'go@1.25.0')"
  parse_publish_result "${out}"
  [ "${RESULT_RC}" -eq 1 ] || problems="${problems} exit=${RESULT_RC}"
  [ "$(cat "${RESULT_ROOT}/state/builds" 2> /dev/null)" = 'go@1.25.0' ] \
    || problems="${problems} symlink-preflight-did-not-build"
  [ "$(count_calls "${RESULT_ROOT}/state/artifact-checks" 'storage.py artifact-exists')" -eq 2 ] \
    || problems="${problems} verification-count"
  grep -q 'simulated symlink-only artifact' "${RESULT_ROOT}/state/alert-logs" 2> /dev/null \
    || problems="${problems} symlink-log-not-passed-to-alert"
  [ "$(count_calls "${RESULT_ROOT}/state/abandons" 'reconcile.py abandon')" -eq 1 ] \
    || problems="${problems} abandon-not-called"
  report_publish_result "publish symlink-only result fails verification" "${RESULT_ROOT}" "${problems}"
}

test_publish_post_upload_verification_error_fails_and_abandons() {
  local out problems=""
  out="$(PUBLISH_TEST_ARTIFACT_BEFORE=1 PUBLISH_TEST_ARTIFACT_AFTER=2 \
    run_publish "$(mktemp -d)" 'nginx@1.31.8')"
  parse_publish_result "${out}"
  [ "${RESULT_RC}" -eq 2 ] || problems="${problems} exit=${RESULT_RC}"
  [ "$(count_calls "${RESULT_ROOT}/state/alerts" 'reconcile.py alert')" -eq 1 ] \
    || problems="${problems} alert-not-called"
  grep -q 'simulated artifact verification error' "${RESULT_ROOT}/state/alert-logs" 2> /dev/null \
    || problems="${problems} verification-log-not-passed-to-alert"
  [ "$(count_calls "${RESULT_ROOT}/state/abandons" 'reconcile.py abandon')" -eq 1 ] \
    || problems="${problems} abandon-not-called"
  [ ! -s "${RESULT_ROOT}/state/successes" ] || problems="${problems} unexpected-resolve"
  report_publish_result "publish post-upload verification error fails and abandons" "${RESULT_ROOT}" "${problems}"
}

test_publish_preflight_verification_error_does_not_build() {
  local out problems=""
  out="$(PUBLISH_TEST_ARTIFACT_BEFORE=2 run_publish "$(mktemp -d)" 'nginx@1.31.8')"
  parse_publish_result "${out}"
  [ "${RESULT_RC}" -eq 2 ] || problems="${problems} exit=${RESULT_RC}"
  [ ! -s "${RESULT_ROOT}/state/builds" ] || problems="${problems} built-after-verification-error"
  [ ! -s "${RESULT_ROOT}/state/uploads" ] || problems="${problems} uploaded-after-verification-error"
  [ "$(count_calls "${RESULT_ROOT}/state/alerts" 'reconcile.py alert')" -eq 1 ] \
    || problems="${problems} alert-not-called"
  [ "$(count_calls "${RESULT_ROOT}/state/abandons" 'reconcile.py abandon')" -eq 1 ] \
    || problems="${problems} abandon-not-called"
  report_publish_result "publish preflight verification error does not build" "${RESULT_ROOT}" "${problems}"
}

test_publish_image_build_failure_preserves_status_and_abandons() {
  local out problems=""
  out="$(PUBLISH_TEST_IMAGE_BUILD_RC=31 run_publish "$(mktemp -d)" 'nginx@1.31.8')"
  parse_publish_result "${out}"
  [ "${RESULT_RC}" -eq 31 ] || problems="${problems} exit=${RESULT_RC}"
  [ ! -s "${RESULT_ROOT}/state/artifact-checks" ] || problems="${problems} preflight-after-image-failure"
  [ ! -s "${RESULT_ROOT}/state/builds" ] || problems="${problems} stack-build-after-image-failure"
  [ "$(count_calls "${RESULT_ROOT}/state/alerts" 'reconcile.py alert')" -eq 1 ] \
    || problems="${problems} alert-not-called"
  grep -q 'simulated buildpack image failure' "${RESULT_ROOT}/state/alert-logs" 2> /dev/null \
    || problems="${problems} image-log-not-passed-to-alert"
  [ "$(count_calls "${RESULT_ROOT}/state/abandons" 'reconcile.py abandon')" -eq 1 ] \
    || problems="${problems} abandon-not-called"
  report_publish_result "publish image build failure preserves status and abandons" \
    "${RESULT_ROOT}" "${problems}"
}

test_publish_build_failure_preserves_status_logs_and_abandons_after_alert_failure() {
  local out problems="" alert_line abandon_line
  out="$(PUBLISH_TEST_ARTIFACT_BEFORE=1 PUBLISH_TEST_BUILD_RC=37 \
    PUBLISH_TEST_ALERT_RC=19 PUBLISH_TEST_ABANDON_MODE=404 \
    run_publish "$(mktemp -d)" 'nginx@1.31.8')"
  parse_publish_result "${out}"
  [ "${RESULT_RC}" -eq 37 ] || problems="${problems} exit=${RESULT_RC}"
  [ ! -s "${RESULT_ROOT}/state/uploads" ] || problems="${problems} upload-after-build-failure"
  [ "$(count_calls "${RESULT_ROOT}/state/artifact-checks" 'storage.py artifact-exists')" -eq 1 ] \
    || problems="${problems} verification-count"
  [ "$(count_calls "${RESULT_ROOT}/state/alerts" 'reconcile.py alert')" -eq 1 ] \
    || problems="${problems} alert-not-called"
  grep -q 'simulated build failure for nginx@1.31.8' "${RESULT_ROOT}/state/alert-logs" 2> /dev/null \
    || problems="${problems} build-log-not-passed-to-alert"
  grep -q 'simulated build failure for nginx@1.31.8' "${RESULT_ROOT}/out.log" \
    || problems="${problems} build-log-not-streamed"
  [ "$(count_calls "${RESULT_ROOT}/state/abandons" 'reconcile.py abandon')" -eq 1 ] \
    || problems="${problems} alert-failure-prevented-abandon"
  grep -q 'already absent (404)' "${RESULT_ROOT}/out.log" \
    || problems="${problems} second-delete-404-not-accepted"
  alert_line="$(grep -n 'reconcile.py alert' "${RESULT_ROOT}/state/invocations" 2> /dev/null | cut -d: -f1)"
  abandon_line="$(grep -n 'reconcile.py abandon' "${RESULT_ROOT}/state/invocations" 2> /dev/null | cut -d: -f1)"
  [ -n "${alert_line}" ] && [ -n "${abandon_line}" ] && [ "${alert_line}" -lt "${abandon_line}" ] \
    || problems="${problems} alert-abandon-order"
  [ ! -s "${RESULT_ROOT}/state/successes" ] || problems="${problems} unexpected-resolve"
  report_publish_result "publish build failure preserves status logs and abandons after alert failure" \
    "${RESULT_ROOT}" "${problems}"
}

test_publish_upload_failure_preserves_status_despite_abandon_failure() {
  local out problems=""
  out="$(PUBLISH_TEST_ARTIFACT_BEFORE=1 PUBLISH_TEST_UPLOAD_RC=29 \
    PUBLISH_TEST_ABANDON_RC=41 run_publish "$(mktemp -d)" 'nginx@1.31.8')"
  parse_publish_result "${out}"
  [ "${RESULT_RC}" -eq 29 ] || problems="${problems} exit=${RESULT_RC}"
  [ "$(count_calls "${RESULT_ROOT}/state/alerts" 'reconcile.py alert')" -eq 1 ] \
    || problems="${problems} alert-not-called"
  grep -q 'simulated upload failure' "${RESULT_ROOT}/state/alert-logs" 2> /dev/null \
    || problems="${problems} upload-log-not-passed-to-alert"
  [ "$(count_calls "${RESULT_ROOT}/state/abandons" 'reconcile.py abandon')" -eq 1 ] \
    || problems="${problems} abandon-not-called"
  [ "$(count_calls "${RESULT_ROOT}/state/artifact-checks" 'storage.py artifact-exists')" -eq 1 ] \
    || problems="${problems} verified-after-upload-failure"
  report_publish_result "publish upload failure preserves status despite abandon failure" \
    "${RESULT_ROOT}" "${problems}"
}

test_publish_existing_resolve_failure_retains_tag_and_returns_success() {
  local out problems=""
  out="$(PUBLISH_TEST_ARTIFACT_BEFORE=0 PUBLISH_TEST_SUCCESS_RC=23 \
    run_publish "$(mktemp -d)" 'nginx@1.31.8')"
  parse_publish_result "${out}"
  [ "${RESULT_RC}" -eq 0 ] || problems="${problems} exit=${RESULT_RC}"
  [ "$(count_calls "${RESULT_ROOT}/state/successes" 'reconcile.py success')" -eq 1 ] \
    || problems="${problems} resolve-not-called"
  [ ! -s "${RESULT_ROOT}/state/abandons" ] || problems="${problems} tag-abandoned-after-resolve-failure"
  [ ! -s "${RESULT_ROOT}/state/requests" ] || problems="${problems} tag-recreated-after-resolve-failure"
  [ ! -s "${RESULT_ROOT}/state/alerts" ] || problems="${problems} unexpected-alert"
  report_publish_result "publish existing resolve failure retains tag and returns success" \
    "${RESULT_ROOT}" "${problems}"
}

test_publish_verified_resolve_failure_retains_tag_and_returns_success() {
  local out problems=""
  out="$(PUBLISH_TEST_ARTIFACT_BEFORE=1 PUBLISH_TEST_ARTIFACT_AFTER=0 \
    PUBLISH_TEST_SUCCESS_RC=23 run_publish "$(mktemp -d)" 'nginx@1.31.8')"
  parse_publish_result "${out}"
  [ "${RESULT_RC}" -eq 0 ] || problems="${problems} exit=${RESULT_RC}"
  [ "$(count_calls "${RESULT_ROOT}/state/uploads" 'storage.py upload')" -eq 1 ] \
    || problems="${problems} upload-not-called"
  [ "$(count_calls "${RESULT_ROOT}/state/successes" 'reconcile.py success')" -eq 1 ] \
    || problems="${problems} resolve-not-called"
  [ ! -s "${RESULT_ROOT}/state/abandons" ] || problems="${problems} tag-abandoned-after-resolve-failure"
  [ ! -s "${RESULT_ROOT}/state/requests" ] || problems="${problems} tag-recreated-after-resolve-failure"
  report_publish_result "publish verified resolve failure retains tag and returns success" \
    "${RESULT_ROOT}" "${problems}"
}

test_publish_rejects_malformed_and_removed_stack_tags_before_podman() {
  local tag out root problems
  for tag in 'not-a-tag' 'nginx@' '@1.31.8' 'nginx@1@2' 'nginx/extra@1.31.8'; do
    root="$(mktemp -d)"
    out="$(run_publish "${root}" "${tag}")"
    parse_publish_result "${out}"
    problems=""
    [ "${RESULT_RC}" -ne 0 ] || problems="${problems} malformed-tag-accepted"
    [ ! -e "${RESULT_ROOT}/state/invocations" ] || problems="${problems} podman-called-for-malformed-tag"
    grep -q 'invalid tag' "${RESULT_ROOT}/out.log" || problems="${problems} validation-error-missing"
    if [ -n "${problems}" ]; then
      report_publish_result "publish rejects malformed and removed-stack tags before podman" \
        "${RESULT_ROOT}" "${tag}:${problems}"
      return
    fi
    rm -rf "${RESULT_ROOT}"
  done
  root="$(mktemp -d)"
  out="$(run_publish "${root}" 'removed-stack@1.31.8')"
  parse_publish_result "${out}"
  problems=""
  [ "${RESULT_RC}" -ne 0 ] || problems="${problems} removed-stack-accepted"
  [ ! -e "${RESULT_ROOT}/state/invocations" ] || problems="${problems} podman-called-for-removed-stack"
  grep -q 'unknown stack' "${RESULT_ROOT}/out.log" || problems="${problems} removed-stack-error-missing"
  report_publish_result "publish rejects malformed and removed-stack tags before podman" \
    "${RESULT_ROOT}" "${problems}"
}

main() {
  test_ci_test_uses_buildpack_image
  test_reconcile_request_returns_the_underlying_command_status
  test_reconcile_requests_each_planned_item_without_building
  test_reconcile_request_failure_continues_and_cleans_before_exiting_non_zero
  test_reconcile_with_empty_plan_requests_nothing
  test_reconcile_dry_run_prints_the_plan_without_requesting
  test_reconcile_forwards_planner_arguments
  test_retention_generation_failure_skips_cleaner
  test_reconcile_cleaner_failure_fails_the_run
  test_cleaner_dry_run_also_disables_obsolete_tag_deletion
  test_reconcile_obsolete_tag_cleanup_failure_fails_the_run
  test_reconcile_clean_reconciles_issues_after_tag_cleanup
  test_reconcile_clean_forwards_dry_run_to_issue_reconciliation
  test_reconcile_issue_reconciliation_failure_fails_the_run
  test_run_logged_appends_and_returns_the_command_status
  test_publish_existing_artifact_skips_build_and_resolves
  test_publish_defaults_to_ci_tag_and_builds_missing_artifact
  test_publish_noop_upload_fails_alerts_and_abandons
  test_publish_symlink_only_result_fails_verification
  test_publish_post_upload_verification_error_fails_and_abandons
  test_publish_preflight_verification_error_does_not_build
  test_publish_image_build_failure_preserves_status_and_abandons
  test_publish_build_failure_preserves_status_logs_and_abandons_after_alert_failure
  test_publish_upload_failure_preserves_status_despite_abandon_failure
  test_publish_existing_resolve_failure_retains_tag_and_returns_success
  test_publish_verified_resolve_failure_retains_tag_and_returns_success
  test_publish_rejects_malformed_and_removed_stack_tags_before_podman

  echo
  echo "${passed} passed, ${failed} failed"
  [ "${failed}" -eq 0 ]
}

main "$@"
