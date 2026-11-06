#!/usr/bin/env bash
# tests/test_build.sh
#
# Executor tests for the "reconcile" entry of build.sh:
#   - plan inside the buildpack image, build each planned item via
#     "bash build.sh all stack@version"
#   - one buildpack-dep image per run, reused for every item
#   - a failing item must not stop the remaining items, but the run
#     must exit non-zero
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
# under <root>/state (builds, uploads, planner args) and serves the plan
# from <root>/plan; a build whose STACK_VERSION equals
# RECONCILE_TEST_FAIL_VERSION fails.
make_fake_podman() {
  local root="$1"
  mkdir -p "${root}/bin"
  cat > "${root}/bin/podman" <<'EOF'
#!/usr/bin/env bash
set -u
case " $* " in
  *" build "*)
    echo "image-build" >> "${RECONCILE_TEST_STATE}/buildpack-builds"
    exit 0
    ;;
  *"reconcile.py alert"*)
    echo "$*" >> "${RECONCILE_TEST_STATE}/alerts"
    exit 0
    ;;
  *"reconcile.py success"*)
    echo "$*" >> "${RECONCILE_TEST_STATE}/successes"
    exit 0
    ;;
  *"reconcile.py"*)
    echo "$*" >> "${RECONCILE_TEST_STATE}/plans"
    cat "${RECONCILE_TEST_PLAN}"
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
    export RECONCILE_DRY_RUN="${dry_run}"
    export PATH="${root}/bin:${PATH}"
    # shellcheck source=/dev/null
    . "${REPO}/build.sh"
    reconcile "$@"
  ) > "${root}/out.log" 2>&1 || rc=$?
  local builds uploads image_builds
  builds="$(cat "${root}/state/builds" 2> /dev/null | paste -sd, -)"
  uploads="$(grep -c . "${root}/state/uploads" 2> /dev/null || echo 0)"
  image_builds="$(grep -c . "${root}/state/buildpack-builds" 2> /dev/null || echo 0)"
  echo "${rc}|${builds}|${uploads}|${image_builds}|${root}"
}

count_calls() {
  # count_calls <file> <pattern>: number of recorded invocations matching
  grep -c -- "${2}" "${1}" 2> /dev/null || echo 0
}

parse_result() {
  IFS='|' read -r RESULT_RC RESULT_BUILDS RESULT_UPLOADS RESULT_IMAGE_BUILDS RESULT_ROOT <<< "$1"
}

show_log_on_failure() {
  local problems="$1"
  echo "  reconcile:${problems}" >&2
  sed 's/^/    /' "${RESULT_ROOT}/out.log" >&2
  rm -rf "${RESULT_ROOT}"
  return 1
}

test_reconcile_builds_each_planned_item_and_reuses_the_image() {
  local out problems=""
  out="$(run_reconcile "$(mktemp -d)" $'nginx@1.31.8\nrustfs@1.0.4\n' '' '')"
  parse_result "${out}"
  [ "${RESULT_RC}" -eq 0 ] || problems="${problems} exit=${RESULT_RC}"
  [ "${RESULT_IMAGE_BUILDS}" -eq 1 ] || problems="${problems} image_builds=${RESULT_IMAGE_BUILDS}"
  [ "${RESULT_BUILDS}" = "nginx@1.31.8,rustfs@1.0.4" ] || problems="${problems} builds=[${RESULT_BUILDS}]"
  [ "${RESULT_UPLOADS}" -eq 2 ] || problems="${problems} uploads=${RESULT_UPLOADS}"
  grep -q "ok=2 failed=0" "${RESULT_ROOT}/out.log" || problems="${problems} summary-missing"
  [ "$(count_calls "${RESULT_ROOT}/state/successes" "reconcile.py success")" -eq 2 ] \
    || problems="${problems} successes=$(count_calls "${RESULT_ROOT}/state/successes" "reconcile.py success")"
  grep -q -- "--stack nginx --version 1.31.8" "${RESULT_ROOT}/state/successes" 2> /dev/null \
    || problems="${problems} success-nginx-missing"
  grep -q -- "--env CI_COMMIT_SHA=" "${RESULT_ROOT}/state/successes" 2> /dev/null \
    || problems="${problems} commit-sha-not-forwarded"
  [ "$(count_calls "${RESULT_ROOT}/state/alerts" "reconcile.py alert")" -eq 0 ] \
    || problems="${problems} unexpected-alert"
  if [ -z "${problems}" ]; then
    report "reconcile builds each planned item and reuses the image" 0
    rm -rf "${RESULT_ROOT}"
  else
    show_log_on_failure "${problems}" || true
    report "reconcile builds each planned item and reuses the image" 1
  fi
}

test_reconcile_continues_after_a_failure_and_exits_non_zero() {
  local out problems=""
  out="$(run_reconcile "$(mktemp -d)" $'nginx@1.31.8\nbadstack@9.9.9\n' '9.9.9' '')"
  parse_result "${out}"
  [ "${RESULT_RC}" -ne 0 ] || problems="${problems} exit=0"
  [ "${RESULT_IMAGE_BUILDS}" -eq 1 ] || problems="${problems} image_builds=${RESULT_IMAGE_BUILDS}"
  [ "${RESULT_BUILDS}" = "nginx@1.31.8,badstack@9.9.9" ] || problems="${problems} builds=[${RESULT_BUILDS}]"
  [ "${RESULT_UPLOADS}" -eq 1 ] || problems="${problems} uploads=${RESULT_UPLOADS}"
  grep -q "ok=1 failed=1" "${RESULT_ROOT}/out.log" || problems="${problems} summary-missing"
  [ "$(count_calls "${RESULT_ROOT}/state/alerts" "reconcile.py alert")" -eq 1 ] \
    || problems="${problems} alerts=$(count_calls "${RESULT_ROOT}/state/alerts" "reconcile.py alert")"
  grep -q -- "--stack badstack --version 9.9.9" "${RESULT_ROOT}/state/alerts" 2> /dev/null \
    || problems="${problems} alert-badstack-missing"
  [ "$(count_calls "${RESULT_ROOT}/state/successes" "reconcile.py success")" -eq 1 ] \
    || problems="${problems} successes=$(count_calls "${RESULT_ROOT}/state/successes" "reconcile.py success")"
  if [ -z "${problems}" ]; then
    report "reconcile continues after a failure and exits non-zero" 0
    rm -rf "${RESULT_ROOT}"
  else
    show_log_on_failure "${problems}" || true
    report "reconcile continues after a failure and exits non-zero" 1
  fi
}

test_reconcile_without_github_token_skips_reporting() {
  local out problems=""
  out="$(GITHUB_TOKEN= run_reconcile "$(mktemp -d)" $'nginx@1.31.8\nbadstack@9.9.9\n' '9.9.9' '')"
  parse_result "${out}"
  [ "${RESULT_RC}" -ne 0 ] || problems="${problems} exit=0"
  [ -z "$(cat "${RESULT_ROOT}/state/alerts" 2> /dev/null)" ] \
    || problems="${problems} alerts-should-be-empty"
  [ -z "$(cat "${RESULT_ROOT}/state/successes" 2> /dev/null)" ] \
    || problems="${problems} successes-should-be-empty"
  grep -q "ok=1 failed=1" "${RESULT_ROOT}/out.log" || problems="${problems} summary-missing"
  if [ -z "${problems}" ]; then
    report "reconcile without github token skips reporting" 0
    rm -rf "${RESULT_ROOT}"
  else
    show_log_on_failure "${problems}" || true
    report "reconcile without github token skips reporting" 1
  fi
}

test_reconcile_with_empty_plan_builds_nothing() {
  local out problems=""
  out="$(run_reconcile "$(mktemp -d)" '' '' '')"
  parse_result "${out}"
  [ "${RESULT_RC}" -eq 0 ] || problems="${problems} exit=${RESULT_RC}"
  [ -z "${RESULT_BUILDS}" ] || problems="${problems} builds=[${RESULT_BUILDS}]"
  [ "${RESULT_UPLOADS}" -eq 0 ] || problems="${problems} uploads=${RESULT_UPLOADS}"
  [ "${RESULT_IMAGE_BUILDS}" -eq 1 ] || problems="${problems} image_builds=${RESULT_IMAGE_BUILDS}"
  grep -q "nothing to build" "${RESULT_ROOT}/out.log" || problems="${problems} message-missing"
  if [ -z "${problems}" ]; then
    report "reconcile with empty plan builds nothing" 0
    rm -rf "${RESULT_ROOT}"
  else
    show_log_on_failure "${problems}" || true
    report "reconcile with empty plan builds nothing" 1
  fi
}

test_reconcile_dry_run_prints_the_plan_without_building() {
  local out problems=""
  out="$(run_reconcile "$(mktemp -d)" $'nginx@1.31.8\nrustfs@1.0.4\n' '' '1')"
  parse_result "${out}"
  [ "${RESULT_RC}" -eq 0 ] || problems="${problems} exit=${RESULT_RC}"
  [ -z "${RESULT_BUILDS}" ] || problems="${problems} builds=[${RESULT_BUILDS}]"
  [ "${RESULT_UPLOADS}" -eq 0 ] || problems="${problems} uploads=${RESULT_UPLOADS}"
  [ "${RESULT_IMAGE_BUILDS}" -eq 1 ] || problems="${problems} image_builds=${RESULT_IMAGE_BUILDS}"
  grep -q "dry run" "${RESULT_ROOT}/out.log" || problems="${problems} dry-run-message-missing"
  grep -q "nginx@1.31.8" "${RESULT_ROOT}/out.log" || problems="${problems} plan-items-missing"
  grep -q "rustfs@1.0.4" "${RESULT_ROOT}/out.log" || problems="${problems} plan-items-missing"
  grep -q "reconcile: building" "${RESULT_ROOT}/out.log" && problems="${problems} unexpected-build-attempt"
  if [ -z "${problems}" ]; then
    report "reconcile dry run prints the plan without building" 0
    rm -rf "${RESULT_ROOT}"
  else
    show_log_on_failure "${problems}" || true
    report "reconcile dry run prints the plan without building" 1
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

main() {
  test_reconcile_builds_each_planned_item_and_reuses_the_image
  test_reconcile_continues_after_a_failure_and_exits_non_zero
  test_reconcile_with_empty_plan_builds_nothing
  test_reconcile_dry_run_prints_the_plan_without_building
  test_reconcile_forwards_planner_arguments
  test_reconcile_without_github_token_skips_reporting

  echo
  echo "${passed} passed, ${failed} failed"
  [ "${failed}" -eq 0 ]
}

main "$@"
