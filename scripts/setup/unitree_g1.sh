#!/bin/sh

set -eu

USER_NAME="unitree"
USER_HOME="/home/${USER_NAME}"
ROBOCLAW_REPO_URL="https://github.com/spin-matrix/roboclaw.git"
ROBOCLAW_DIR="${USER_HOME}/roboclaw"
ROBOT_GRASP_SCRIPTS_DIR="${ROBOCLAW_DIR}/nanobot/skills/robot-grasp/scripts"
CYCLONEDDS_REPO_URL="https://gh-proxy.org/https://github.com/eclipse-cyclonedds/cyclonedds.git"
CYCLONEDDS_BRANCH="releases/0.10.x"
CYCLONEDDS_DIR="${USER_HOME}/cyclonedds"
MINICONDA_DIR="${USER_HOME}/miniconda3"
MINICONDA_INSTALLER="${USER_HOME}/miniconda.sh"
IK_ENV_NAME="ik_env"
TORCHVISION_REPO_URL="https://gh-proxy.org/https://github.com/pytorch/vision.git"
TORCHVISION_TAG="v0.15.1"
TORCHVISION_DIR="${ROBOT_GRASP_SCRIPTS_DIR}/vision"
UNITREE_SDK2_REPO_URL="https://github.com/unitreerobotics/unitree_sdk2.git"
UNITREE_SDK2_DIR="${USER_HOME}/unitree_sdk2"
SYSTEMD_USER_DIR="${USER_HOME}/.config/systemd/user"
LOCAL_BIN="${USER_HOME}/.local/bin"
PROFILE_ENV_FILE="${USER_HOME}/.profile"

log() {
    printf '==> %s\n' "$*"
}

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

require_env() {
    var_name="$1"
    eval "var_value=\${$var_name-}"
    if [ -z "${var_value}" ]; then
        fail "environment variable ${var_name} is required"
    fi
}

as_root() {
    require_env "PASSWORD"
    printf '%s\n' "$PASSWORD" | sudo -S -p '' "$@"
}

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

cpu_count() {
    getconf _NPROCESSORS_ONLN 2>/dev/null || echo 4
}

ensure_running_as_unitree() {
    current_user="$(id -un)"
    if [ "${current_user}" != "${USER_NAME}" ]; then
        fail "this script must run as ${USER_NAME}, current user is ${current_user}"
    fi
}

ensure_sudo_ready() {
    if ! command_exists sudo; then
        fail "sudo is required but not installed"
    fi
    as_root true >/dev/null 2>&1
}

apt_install() {
    export DEBIAN_FRONTEND=noninteractive
    as_root apt-get update
    as_root apt-get install -y "$@"
}

ensure_base_packages() {
    log "Installing base packages"
    apt_install \
        ca-certificates \
        curl \
        git \
        sudo \
        build-essential \
        cmake \
        g++ \
        pkg-config \
        python3 \
        python3-dev \
        python3-venv \
        libyaml-cpp-dev \
        libeigen3-dev \
        libboost-all-dev \
        libjpeg-dev \
        libopenblas-dev \
        libpng-dev \
        libspdlog-dev \
        libtiff-dev \
        libfmt-dev \
        libusb-1.0-0-dev \
        libturbojpeg-dev
}

ensure_uv() {
    export PATH="${LOCAL_BIN}:${PATH}"
    if command_exists uv; then
        return
    fi

    log "Installing uv"
    mkdir -p "${LOCAL_BIN}"
    curl -LsSf https://astral.sh/uv/install.sh | env UV_UNMANAGED_INSTALL="${LOCAL_BIN}" sh
}

ensure_repo_checkout() {
    repo_url="$1"
    repo_dir="$2"
    repo_ref="${3-}"

    if [ -d "${repo_dir}/.git" ]; then
        log "Updating repository ${repo_dir}"
        git -C "${repo_dir}" remote set-url origin "${repo_url}"
        if [ -n "${repo_ref}" ]; then
            git -C "${repo_dir}" fetch --depth 1 origin "${repo_ref}"
            if git -C "${repo_dir}" show-ref --verify --quiet "refs/heads/${repo_ref}"; then
                git -C "${repo_dir}" checkout "${repo_ref}"
            else
                git -C "${repo_dir}" checkout -b "${repo_ref}" "origin/${repo_ref}"
            fi
            git -C "${repo_dir}" pull --ff-only origin "${repo_ref}"
        else
            git -C "${repo_dir}" fetch --depth 1 origin
            current_branch="$(git -C "${repo_dir}" rev-parse --abbrev-ref HEAD)"
            git -C "${repo_dir}" pull --ff-only origin "${current_branch}"
        fi
        return
    fi

    if [ -e "${repo_dir}" ]; then
        fail "${repo_dir} exists but is not a git repository"
    fi

    log "Cloning ${repo_url} -> ${repo_dir}"
    if [ -n "${repo_ref}" ]; then
        git clone --depth 1 --branch "${repo_ref}" "${repo_url}" "${repo_dir}"
    else
        git clone --depth 1 "${repo_url}" "${repo_dir}"
    fi
}

set_export_in_file() {
    var_name="$1"
    var_value="$2"
    target_file="$3"
    tmp_file="$(mktemp)"

    mkdir -p "$(dirname "${target_file}")"
    touch "${target_file}"

    grep -v "^export ${var_name}=" "${target_file}" > "${tmp_file}" || true
    printf 'export %s="%s"\n' "${var_name}" "${var_value}" >> "${tmp_file}"
    mv "${tmp_file}" "${target_file}"
}

ensure_line_in_file() {
    line="$1"
    target_file="$2"

    mkdir -p "$(dirname "${target_file}")"
    touch "${target_file}"

    if grep -Fqx "${line}" "${target_file}"; then
        return
    fi

    printf '%s\n' "${line}" >> "${target_file}"
}

miniconda_url() {
    arch="$(uname -m)"

    case "${arch}" in
        x86_64|amd64)
            printf '%s\n' "https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh"
            ;;
        aarch64|arm64)
            printf '%s\n' "https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh"
            ;;
        *)
            fail "unsupported architecture for miniconda installer: ${arch}"
            ;;
    esac
}

ensure_cyclonedds() {
    log "Installing cyclonedds"
    ensure_repo_checkout "${CYCLONEDDS_REPO_URL}" "${CYCLONEDDS_DIR}" "${CYCLONEDDS_BRANCH}"

    mkdir -p "${CYCLONEDDS_DIR}/build" "${CYCLONEDDS_DIR}/install"
    cmake -S "${CYCLONEDDS_DIR}" -B "${CYCLONEDDS_DIR}/build" -DCMAKE_INSTALL_PREFIX="${CYCLONEDDS_DIR}/install"
    cmake --build "${CYCLONEDDS_DIR}/build" --target install -j"$(cpu_count)"

    export CYCLONEDDS_HOME="$(realpath "${CYCLONEDDS_DIR}/install")"
    set_export_in_file "CYCLONEDDS_HOME" "${CYCLONEDDS_HOME}" "${PROFILE_ENV_FILE}"
}

ensure_miniconda() {
    if [ -x "${MINICONDA_DIR}/bin/conda" ]; then
        log "miniconda already installed at ${MINICONDA_DIR}"
    else
        log "Installing miniconda"
        curl -LsSf "$(miniconda_url)" -o "${MINICONDA_INSTALLER}"
        sh "${MINICONDA_INSTALLER}" -b -p "${MINICONDA_DIR}"
        rm -f "${MINICONDA_INSTALLER}"
    fi

    export PATH="${MINICONDA_DIR}/bin:${PATH}"
    ensure_line_in_file "export PATH=\"${MINICONDA_DIR}/bin:\$PATH\"" "${PROFILE_ENV_FILE}"
}

ensure_ik_env() {
    log "Ensuring conda environment ${IK_ENV_NAME} is available"

    if "${MINICONDA_DIR}/bin/conda" env list | awk '{print $1}' | grep -Fxq "${IK_ENV_NAME}"; then
        log "conda environment ${IK_ENV_NAME} already exists"
    else
        "${MINICONDA_DIR}/bin/conda" create -y -n "${IK_ENV_NAME}" casadi=3.6.5 pinocchio=3.2.0 -c conda-forge
    fi

    "${MINICONDA_DIR}/bin/conda" run -n "${IK_ENV_NAME}" pip install fastapi uvicorn matplotlib
}

ensure_robot_grasp_torchvision() {
    venv_python="${ROBOT_GRASP_SCRIPTS_DIR}/.venv/bin/python"

    if [ ! -x "${venv_python}" ]; then
        fail "robot-grasp virtualenv python not found at ${venv_python}"
    fi

    log "Installing torchvision into ${ROBOT_GRASP_SCRIPTS_DIR}/.venv"
    if [ -d "${TORCHVISION_DIR}/.git" ]; then
        git -C "${TORCHVISION_DIR}" remote set-url origin "${TORCHVISION_REPO_URL}"
        git -C "${TORCHVISION_DIR}" fetch --tags origin
    elif [ -e "${TORCHVISION_DIR}" ]; then
        fail "${TORCHVISION_DIR} exists but is not a git repository"
    else
        git clone "${TORCHVISION_REPO_URL}" "${TORCHVISION_DIR}"
        git -C "${TORCHVISION_DIR}" fetch --tags origin
    fi

    git -C "${TORCHVISION_DIR}" checkout "tags/${TORCHVISION_TAG}"
    (
        cd "${TORCHVISION_DIR}"
        "${venv_python}" setup.py install
    )
}

enable_user_linger() {
    log "Enabling linger for ${USER_NAME}"
    as_root loginctl enable-linger "${USER_NAME}"
}

ensure_unitree_sdk2() {
    if [ -x "/usr/local/bin/g1_loco_client" ] && [ -x "/usr/local/bin/g1_arm_action" ]; then
        log "unitree_sdk2 binaries already present"
        return
    fi

    log "Installing unitree_sdk2"
    ensure_repo_checkout "${UNITREE_SDK2_REPO_URL}" "${UNITREE_SDK2_DIR}"

    mkdir -p "${UNITREE_SDK2_DIR}/build"
    cmake -S "${UNITREE_SDK2_DIR}" -B "${UNITREE_SDK2_DIR}/build" -DCMAKE_BUILD_TYPE=Release
    cmake --build "${UNITREE_SDK2_DIR}/build" -j"$(cpu_count)"
    as_root cmake --install "${UNITREE_SDK2_DIR}/build"
    as_root install -m 0755 "${UNITREE_SDK2_DIR}/build/bin/g1_loco_client" /usr/local/bin/g1_loco_client
    as_root install -m 0755 "${UNITREE_SDK2_DIR}/build/bin/g1_arm_action_example" /usr/local/bin/g1_arm_action
    as_root install -m 0755 "${UNITREE_SDK2_DIR}/build/bin/g1_audio_client_example" /usr/local/bin/g1_audio_client
    as_root ldconfig
}

ensure_uv_python() {
    log "Ensuring uv-managed Python is available"
    uv python install
}

sync_project_env() {
    project_dir="$1"
    extra_arg="${2-}"

    ensure_uv_python
    log "Syncing dependencies in ${project_dir}"
    if [ -n "${extra_arg}" ]; then
        (
            cd "${project_dir}"
            uv sync "${extra_arg}"
        )
    else
        (
            cd "${project_dir}"
            uv sync
        )
    fi
}

install_user_service() {
    service_name="$1"
    source_file="$2"

    mkdir -p "${SYSTEMD_USER_DIR}"
    install -m 0644 "${source_file}" "${SYSTEMD_USER_DIR}/${service_name}"
}

prepare_user_systemd_env() {
    user_id="$(id -u "${USER_NAME}")"
    export XDG_RUNTIME_DIR="/run/user/${user_id}"
    if [ -S "${XDG_RUNTIME_DIR}/bus" ]; then
        export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
    fi
}

user_systemctl() {
    prepare_user_systemd_env
    systemctl --user "$@"
}

user_service_active() {
    service_name="$1"
    if user_systemctl is-active --quiet "${service_name}"; then
        return 0
    fi
    return 1
}

ensure_roboclaw_services() {
    if user_service_active roboclaw.service; then
        log "roboclaw.service is already active; refreshing checkout, environments, and service files"
    fi

    log "Installing roboclaw and robot services"
    ensure_repo_checkout "${ROBOCLAW_REPO_URL}" "${ROBOCLAW_DIR}"

    sync_project_env "${ROBOCLAW_DIR}"
    sync_project_env "${ROBOCLAW_DIR}/robot/teleimager" "--extra=server"
    sync_project_env "${ROBOCLAW_DIR}/robot/obstacle_avoid"
    sync_project_env "${ROBOT_GRASP_SCRIPTS_DIR}"
    ensure_robot_grasp_torchvision

    install_user_service "roboclaw.service" "${ROBOCLAW_DIR}/systemd/roboclaw.service"
    install_user_service "teleimager.service" "${ROBOCLAW_DIR}/systemd/teleimager.service"
    install_user_service "obstacle-avoid.service" "${ROBOCLAW_DIR}/systemd/obstacle-avoid.service"
    install_user_service "yolo-detector.service" "${ROBOCLAW_DIR}/systemd/yolo-detector.service"
    install_user_service "arm-ik-server.service" "${ROBOCLAW_DIR}/systemd/arm-ik-server.service"

    user_systemctl daemon-reload
    user_systemctl enable --now roboclaw.service
    user_systemctl enable --now teleimager.service
    user_systemctl enable --now obstacle-avoid.service
    user_systemctl enable --now yolo-detector.service
    user_systemctl enable --now arm-ik-server.service

    user_service_active roboclaw.service || fail "roboclaw.service failed to start"
    user_service_active teleimager.service || fail "teleimager.service failed to start"
    user_service_active obstacle-avoid.service || fail "obstacle-avoid.service failed to start"
    user_service_active yolo-detector.service || fail "yolo-detector.service failed to start"
    user_service_active arm-ik-server.service || fail "arm-ik-server.service failed to start"

    log "roboclaw.service is active"
    log "teleimager.service is active"
    log "obstacle-avoid.service is active"
    log "yolo-detector.service is active"
    log "arm-ik-server.service is active"
}

main() {
    ensure_running_as_unitree
    ensure_sudo_ready
    enable_user_linger
    ensure_base_packages
    ensure_uv
    ensure_uv_python
    ensure_cyclonedds
    ensure_miniconda
    ensure_ik_env
    ensure_unitree_sdk2
    ensure_roboclaw_services
    log "Unitree G1 setup completed successfully"
}

main "$@"
