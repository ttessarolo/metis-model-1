"""L70 native launcher gate: exactly ten local, unprivileged cases.

The C harnesses compile only below pytest's temporary directory.  Credential
and exec syscalls are injected; the child is a tiny in-process native stub.
These tests create no identity, service, key or installed binary and never run
Node/Metis.  Passing them is local simulation, not Phase-B host evidence.
"""

from __future__ import annotations

import hashlib
import os
import plistlib
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_SOURCE = ROOT / "runtime/w3_privileged_launcher.c"
SHIM_SOURCE = ROOT / "runtime/w3_socket_activation_shim.c"
RUNNER_SOURCE = ROOT / "runtime/metis_oracle/runner.ts"
LAUNCHER_PLIST = ROOT / "packaging/launchd/com.metis.model1.w3-launcher.plist.in"
SEATBELT_POLICY = ROOT / "packaging/seatbelt/w3-runner.sb"
INSTALLER_SOURCE = ROOT / "runtime/w3_broker_installer.py"


@dataclass(frozen=True)
class NativeHarnesses:
    launcher: Path
    launcher_socket: Path
    seatbelt_policy: Path
    broker_shim: Path
    anchor_shim: Path


LAUNCHER_HARNESS = r"""
#define setgroups w3_test_setgroups
#define setgid w3_test_setgid
#define setuid w3_test_setuid
#define getgroups w3_test_getgroups
#define getgid w3_test_getgid
#define getegid w3_test_getegid
#define getuid w3_test_getuid
#define geteuid w3_test_geteuid
#define execve w3_test_execve
#define main w3_product_main
#include "__LAUNCHER_SOURCE__"
#undef main
#undef setgroups
#undef setgid
#undef setuid
#undef getgroups
#undef getgid
#undef getegid
#undef getuid
#undef geteuid
#undef execve

static int test_regain_mode = 0;
static int test_exec_mode = 0;
static uid_t test_uid = 0;
static gid_t test_gid = 0;
static int test_group_count = 1;
static char test_order[16];
static size_t test_order_length = 0U;
static int activation_listener = -1;
static size_t activation_count = 1U;
static int activation_error = 0;
static int activation_name_ok = 0;
static char pgid_order[32];
static size_t pgid_order_length = 0U;
static uint32_t pgid_other_members = 0U;
static int pgid_reaped = 0;
static int pgid_echild = 0;
static int pgid_leader_terminal = 1;
static int pgid_post_reap_operation = 0;
static int pgid_group_operation_count = 0;

static void append_pgid_order(char value)
{
    if (pgid_order_length + 1U < sizeof(pgid_order)) {
        pgid_order[pgid_order_length++] = value;
        pgid_order[pgid_order_length] = '\0';
    }
}

static void reset_pgid_ops(uint32_t other_members, int echild)
{
    memset(pgid_order, 0, sizeof(pgid_order));
    pgid_order_length = 0U;
    pgid_other_members = other_members;
    pgid_reaped = 0;
    pgid_echild = echild;
    pgid_leader_terminal = 1;
    pgid_post_reap_operation = 0;
    pgid_group_operation_count = 0;
}

static int fake_observe_leader(pid_t leader, int *terminal_out)
{
    (void)leader;
    if (pgid_reaped) {
        pgid_post_reap_operation = 1;
        errno = ESRCH;
        return -1;
    }
    append_pgid_order('o');
    *terminal_out = pgid_leader_terminal;
    return 0;
}

static int fake_census_group(
    pid_t process_group,
    pid_t leader,
    uint32_t *other_members_out,
    int *leader_present_out
)
{
    (void)process_group;
    (void)leader;
    if (pgid_reaped) {
        pgid_post_reap_operation = 1;
        errno = ESRCH;
        return -1;
    }
    ++pgid_group_operation_count;
    append_pgid_order('c');
    *other_members_out = pgid_other_members;
    *leader_present_out = 1;
    return 0;
}

static int fake_signal_group(pid_t process_group, int signal_number)
{
    (void)process_group;
    if (pgid_reaped) {
        pgid_post_reap_operation = 1;
        errno = ESRCH;
        return -1;
    }
    ++pgid_group_operation_count;
    append_pgid_order(signal_number == SIGTERM ? 't' : 'k');
    pgid_other_members = 0U;
    return 0;
}

static int fake_signal_pid(pid_t process, int signal_number)
{
    (void)process;
    if (pgid_reaped) {
        pgid_post_reap_operation = 1;
        errno = ESRCH;
        return -1;
    }
    append_pgid_order(signal_number == SIGTERM ? 'p' : 'q');
    pgid_leader_terminal = 1;
    return 0;
}

static int fake_reap_leader(pid_t leader, int *wait_status)
{
    (void)leader;
    append_pgid_order('r');
    if (pgid_echild) {
        errno = ECHILD;
        return -1;
    }
    *wait_status = 0;
    pgid_reaped = 1;
    return 0;
}

static const struct w3_process_ops fake_process_ops = {
    .observe_leader_fn = fake_observe_leader,
    .census_group_fn = fake_census_group,
    .signal_group_fn = fake_signal_group,
    .signal_pid_fn = fake_signal_pid,
    .reap_leader_fn = fake_reap_leader,
};

static void append_order(char value)
{
    if (test_order_length + 1U < sizeof(test_order)) {
        test_order[test_order_length++] = value;
        test_order[test_order_length] = '\0';
    }
}

static void reset_identity(void)
{
    test_uid = 0;
    test_gid = 0;
    test_group_count = 1;
    test_order_length = 0U;
    memset(test_order, 0, sizeof(test_order));
}

int w3_test_setgroups(int count, const gid_t *groups)
{
    (void)groups;
    append_order('a');
    if (count != 0) {
        errno = EINVAL;
        return -1;
    }
    test_group_count = 0;
    return 0;
}

int w3_test_setgid(gid_t gid)
{
    if (gid == W3_RUNNER_GID) {
        append_order('b');
        test_gid = gid;
        return 0;
    }
    if (gid == 0) {
        append_order('e');
        if (test_regain_mode == 2) {
            test_gid = 0;
            return 0;
        }
        if (test_regain_mode == 6) {
            test_gid = 0;
        }
        errno = test_regain_mode == 4 ? EACCES : EPERM;
        return -1;
    }
    errno = EINVAL;
    return -1;
}

int w3_test_setuid(uid_t uid)
{
    if (uid == W3_RUNNER_UID) {
        append_order('c');
        test_uid = uid;
        return 0;
    }
    if (uid == 0) {
        append_order('d');
        if (test_regain_mode == 1) {
            test_uid = 0;
            return 0;
        }
        if (test_regain_mode == 5) {
            test_uid = 0;
        }
        errno = test_regain_mode == 3 ? EACCES : EPERM;
        return -1;
    }
    errno = EINVAL;
    return -1;
}

int w3_test_getgroups(int count, gid_t *groups)
{
    (void)groups;
    if (count != 0) {
        errno = EINVAL;
        return -1;
    }
    return test_group_count;
}

gid_t w3_test_getgid(void) { return test_gid; }
gid_t w3_test_getegid(void) { return test_gid; }
uid_t w3_test_getuid(void) { return test_uid; }
uid_t w3_test_geteuid(void) { return test_uid; }

static int exact_child_boundary(char *const argv[], char *const environment[])
{
    static const char *const expected_argv[] = {
        W3_SANDBOX_EXEC_PATH,
        "-f",
        W3_SEATBELT_POLICY_PATH,
        W3_NODE_PATH,
        "--disable-warning=ExperimentalWarning",
        "--experimental-loader",
        W3_LOADER_PATH,
        W3_RUNNER_PATH,
        "--metis-root",
        W3_METIS_ROOT,
        "--metis-revision",
        W3_METIS_REVISION,
        "--metis-tree",
        W3_METIS_TREE,
        "--loader-path",
        W3_LOADER_PATH,
        "--loader-sha256",
        W3_LOADER_SHA256,
        "--runtime-node-path",
        W3_RUNTIME_NODE_IDENTITY,
        "--node-actual-path",
        W3_NODE_PATH,
        "--runtime-loader-path",
        W3_RUNTIME_LOADER_IDENTITY,
        "--runtime-loader-flags",
        "[\"--disable-warning=ExperimentalWarning\",\"--experimental-loader\"]",
        "--runtime-runner-path",
        W3_RUNTIME_RUNNER_IDENTITY,
        "--runner-actual-path",
        W3_RUNNER_PATH,
        "--snapshot-identity",
        W3_SNAPSHOT_IDENTITY,
        "--node-modules-sha256",
        W3_NODE_MODULES_SHA256,
        "--runner-sha256",
        W3_RUNNER_SHA256,
        "--node-binary-sha256",
        W3_NODE_BINARY_SHA256,
        "--oracle-policy-version",
        W3_ORACLE_POLICY_VERSION,
        "--oracle-policy-sha256",
        W3_ORACLE_POLICY_SHA256,
        "--execution-policy-sha256",
        W3_EXECUTION_POLICY_SHA256,
        "--tooling-package-sha256",
        W3_TOOLING_PACKAGE_SHA256,
        "--tooling-lock-sha256",
        W3_TOOLING_LOCK_SHA256,
        NULL,
    };
    static const char *const expected_environment[] = {
        "HOME=/var/empty",
        "LANG=C",
        "LC_ALL=C",
        "PATH=/usr/bin:/bin",
        "TMPDIR=.",
        "TZ=UTC",
        NULL,
    };
    size_t index;
    int descriptor;

    for (index = 0U; expected_argv[index] != NULL; ++index) {
        if (argv[index] == NULL || strcmp(argv[index], expected_argv[index]) != 0) {
            return 0;
        }
    }
    if (argv[index] != NULL) {
        return 0;
    }
    for (index = 0U; expected_environment[index] != NULL; ++index) {
        if (environment[index] == NULL ||
            strcmp(environment[index], expected_environment[index]) != 0) {
            return 0;
        }
    }
    if (environment[index] != NULL || test_uid != W3_RUNNER_UID ||
        test_gid != W3_RUNNER_GID || test_group_count != 0) {
        return 0;
    }
    for (descriptor = 3; descriptor < 64; ++descriptor) {
        errno = 0;
        if (fcntl(descriptor, F_GETFD) >= 0 || errno != EBADF) {
            return 0;
        }
    }
    return 1;
}

int w3_test_execve(const char *path, char *const argv[], char *const environment[])
{
    uint8_t input[32];
    ssize_t count;

    if (strcmp(path, W3_SANDBOX_EXEC_PATH) != 0 ||
        !exact_child_boundary(argv, environment)) {
        _exit(90);
    }
    if (test_exec_mode == 3) {
        (void)close(STDIN_FILENO);
        (void)write(STDOUT_FILENO, "stub-out", 8U);
        (void)write(STDERR_FILENO, "stub-err", 8U);
        _exit(0);
    }
    do {
        count = read(STDIN_FILENO, input, sizeof(input));
    } while (count > 0 || (count < 0 && errno == EINTR));
    if (test_exec_mode == 1) {
        (void)signal(SIGTERM, SIG_IGN);
        for (;;) {
            pause();
        }
    }
    if (test_exec_mode == 2) {
        uint8_t large[256];
        memset(large, 'x', sizeof(large));
        (void)signal(SIGTERM, SIG_IGN);
        (void)write(STDOUT_FILENO, large, sizeof(large));
        for (;;) {
            pause();
        }
    }
    (void)write(STDOUT_FILENO, "stub-out", 8U);
    (void)write(STDERR_FILENO, "stub-err", 8U);
    _exit(0);
}

static int create_listener(const char *path)
{
    struct sockaddr_un address;
    socklen_t address_length;
    int descriptor = socket(AF_UNIX, SOCK_STREAM, 0);

    if (descriptor < 0 || strlen(path) >= sizeof(address.sun_path)) {
        return -1;
    }
    memset(&address, 0, sizeof(address));
    address.sun_family = AF_UNIX;
    (void)strncpy(address.sun_path, path, sizeof(address.sun_path) - 1U);
    address_length =
        (socklen_t)(offsetof(struct sockaddr_un, sun_path) + strlen(path) + 1U);
#if defined(__APPLE__)
    address.sun_len = (uint8_t)address_length;
#endif
    (void)unlink(path);
    if (bind(descriptor, (struct sockaddr *)&address, address_length) != 0 ||
        listen(descriptor, 4) != 0) {
        (void)close(descriptor);
        return -1;
    }
    return descriptor;
}

static int fake_activate(const char *name, int **descriptors, size_t *count)
{
    size_t index;

    activation_name_ok = strcmp(name, "LauncherListener") == 0;
    if (activation_error != 0) {
        return activation_error;
    }
    *count = activation_count;
    *descriptors = activation_count == 0U ? NULL : calloc(activation_count, sizeof(int));
    if (activation_count != 0U && *descriptors == NULL) {
        return ENOMEM;
    }
    for (index = 0U; index < activation_count; ++index) {
        (*descriptors)[index] = dup(activation_listener);
    }
    return 0;
}

static int scenario_activation(const char *path)
{
    char wrong_path[sizeof(((struct sockaddr_un *)0)->sun_path)];
    int listener;
    int wrong_listener;
    int non_socket;
    int output = -1;
    size_t path_length = strlen(path);

    listener = create_listener(path);
    if (listener < 0) {
        return 10;
    }
    activation_listener = listener;
    activation_count = 1U;
    activation_error = 0;
    if (w3_activate_listener_with(fake_activate, &output) != 0 ||
        !activation_name_ok || output < 0) {
        return 11;
    }
    (void)close(output);
    if (path_length + sizeof(".wrong") > sizeof(wrong_path)) {
        return 12;
    }
    memcpy(wrong_path, path, path_length);
    memcpy(wrong_path + path_length, ".wrong", sizeof(".wrong"));
    wrong_listener = create_listener(wrong_path);
    if (wrong_listener < 0) {
        return 13;
    }
    activation_listener = wrong_listener;
    if (w3_activate_listener_with(fake_activate, &output) == 0) {
        return 14;
    }
    (void)close(wrong_listener);
    (void)unlink(wrong_path);
    non_socket = open("/dev/null", O_RDONLY);
    if (non_socket < 0) {
        return 15;
    }
    activation_listener = non_socket;
    if (w3_activate_listener_with(fake_activate, &output) == 0) {
        return 16;
    }
    (void)close(non_socket);
    activation_listener = listener;
    activation_count = 0U;
    if (w3_activate_listener_with(fake_activate, &output) == 0) {
        return 17;
    }
    activation_count = 2U;
    if (w3_activate_listener_with(fake_activate, &output) == 0) {
        return 18;
    }
    activation_count = 1U;
    activation_error = EALREADY;
    errno = 0;
    if (w3_activate_listener_with(fake_activate, &output) == 0 || errno != EALREADY) {
        return 19;
    }
    (void)close(listener);
    (void)unlink(path);
    puts("activation-ok");
    return 0;
}

static int scenario_peer(void)
{
    int pair[2];
    uid_t uid = W3_BROKER_UID;
    gid_t gid = W3_BROKER_GID;

    if (socketpair(AF_UNIX, SOCK_STREAM, 0, pair) != 0 ||
        w3_authorize_broker_peer_as(pair[0], uid, gid) != 0 ||
        w3_authorize_broker_peer_as(pair[0], uid + 1U, gid) == 0 ||
        w3_authorize_broker_peer_as(pair[0], uid, gid + 1U) == 0) {
        return 20;
    }
    (void)close(pair[0]);
    (void)close(pair[1]);
    puts("peer-ok");
    return 0;
}

static void fill_request_header(struct w3_launcher_request_header *header, uint32_t length)
{
    memset(header, 0, sizeof(*header));
    memcpy(header->magic, W3_LAUNCHER_MAGIC, W3_LAUNCHER_MAGIC_BYTES);
    header->version_be = htonl(W3_LAUNCHER_PROTOCOL_VERSION);
    header->payload_length_be = htonl(length);
    memset(header->request_sha256, 0x11, sizeof(header->request_sha256));
    memset(header->authority_sha256, 0x22, sizeof(header->authority_sha256));
    memset(header->release_sha256, 0x33, sizeof(header->release_sha256));
    memset(header->broker_nonce, 0x44, sizeof(header->broker_nonce));
}

static int write_fragmented(int descriptor, const uint8_t *bytes, size_t length, size_t chunk)
{
    size_t offset = 0U;
    while (offset < length) {
        size_t wanted = length - offset > chunk ? chunk : length - offset;
        ssize_t count = write(descriptor, bytes + offset, wanted);
        if (count > 0) {
            offset += (size_t)count;
        } else if (count < 0 && errno == EINTR) {
            continue;
        } else {
            return -1;
        }
    }
    return 0;
}

static int scenario_frame_valid(void)
{
    int pair[2];
    pid_t writer;
    struct w3_request_frame frame;
    int status = 0;

    if (socketpair(AF_UNIX, SOCK_STREAM, 0, pair) != 0) {
        return 30;
    }
    writer = fork();
    if (writer == 0) {
        struct w3_launcher_request_header header;
        uint8_t chunk[8192];
        uint32_t remaining = W3_LAUNCHER_MAX_PAYLOAD_BYTES;
        fill_request_header(&header, remaining);
        memset(chunk, 0x5a, sizeof(chunk));
        (void)close(pair[0]);
        if (write_fragmented(pair[1], (const uint8_t *)&header, sizeof(header), 7U) != 0) {
            _exit(31);
        }
        while (remaining > 0U) {
            uint32_t amount = remaining > sizeof(chunk) ? (uint32_t)sizeof(chunk) : remaining;
            if (write_fragmented(pair[1], chunk, amount, amount) != 0) {
                _exit(32);
            }
            remaining -= amount;
        }
        (void)shutdown(pair[1], SHUT_WR);
        (void)close(pair[1]);
        _exit(0);
    }
    (void)close(pair[1]);
    if (writer < 0 || w3_receive_request_frame(pair[0], &frame) != 0 ||
        frame.payload_length != W3_LAUNCHER_MAX_PAYLOAD_BYTES ||
        frame.payload[0] != 0x5a || frame.payload[frame.payload_length - 1U] != 0x5a) {
        return 33;
    }
    w3_free_request_frame(&frame);
    (void)close(pair[0]);
    if (waitpid(writer, &status, 0) != writer || !WIFEXITED(status) || WEXITSTATUS(status) != 0) {
        return 34;
    }
    puts("frame-valid-ok");
    return 0;
}

enum bad_frame_mode {
    BAD_MAGIC,
    BAD_VERSION,
    ZERO_LENGTH,
    OVERSIZE_LENGTH,
    TRUNCATED_HEADER,
    TRUNCATED_BODY,
    STALLED_BODY,
    TRAILING_BODY,
    ANCILLARY_RIGHT,
};

static int open_fd_count(void)
{
    int descriptor;
    int count = 0;
    for (descriptor = 0; descriptor < 256; ++descriptor) {
        if (fcntl(descriptor, F_GETFD) >= 0) {
            ++count;
        }
    }
    return count;
}

static void bad_frame_writer(int descriptor, enum bad_frame_mode mode)
{
    struct w3_launcher_request_header header;
    uint8_t body[2] = {0x41, 0x42};

    fill_request_header(&header, 1U);
    if (mode == BAD_MAGIC) {
        header.magic[0] = 'X';
    } else if (mode == BAD_VERSION) {
        header.version_be = htonl(2U);
    } else if (mode == ZERO_LENGTH) {
        header.payload_length_be = htonl(0U);
    } else if (mode == OVERSIZE_LENGTH) {
        header.payload_length_be = htonl(W3_LAUNCHER_MAX_PAYLOAD_BYTES + 1U);
    }
    if (mode == ANCILLARY_RIGHT) {
        union {
            struct cmsghdr alignment;
            uint8_t bytes[CMSG_SPACE(sizeof(int))];
        } control;
        struct iovec vector = {.iov_base = &body[0], .iov_len = 1U};
        struct msghdr message;
        struct cmsghdr *header_control;
        int sent_fd = open("/dev/null", O_RDONLY);
        memset(&control, 0, sizeof(control));
        memset(&message, 0, sizeof(message));
        message.msg_iov = &vector;
        message.msg_iovlen = 1U;
        message.msg_control = control.bytes;
        message.msg_controllen = sizeof(control.bytes);
        header_control = CMSG_FIRSTHDR(&message);
        header_control->cmsg_level = SOL_SOCKET;
        header_control->cmsg_type = SCM_RIGHTS;
        header_control->cmsg_len = CMSG_LEN(sizeof(int));
        memcpy(CMSG_DATA(header_control), &sent_fd, sizeof(sent_fd));
        (void)sendmsg(descriptor, &message, 0);
        (void)close(sent_fd);
    } else if (mode == TRUNCATED_HEADER) {
        (void)write_fragmented(descriptor, (const uint8_t *)&header, sizeof(header) - 1U, 17U);
    } else {
        (void)write_fragmented(descriptor, (const uint8_t *)&header, sizeof(header), 19U);
        if (mode == TRUNCATED_BODY) {
            header.payload_length_be = htonl(2U);
            /* Re-send a correct two-byte-length header on a fresh stream is handled below. */
        }
        if (mode == TRUNCATED_BODY) {
            /* The caller rebuilds this mode with the correct header before invoking us. */
        } else if (mode == TRAILING_BODY) {
            (void)write_fragmented(descriptor, body, 2U, 1U);
        } else if (mode == BAD_MAGIC || mode == BAD_VERSION || mode == ZERO_LENGTH ||
                   mode == OVERSIZE_LENGTH) {
            /* Header rejection happens before a body read. */
        } else {
            (void)write_fragmented(descriptor, body, 1U, 1U);
        }
    }
    (void)shutdown(descriptor, SHUT_WR);
}

static int expect_bad_frame(enum bad_frame_mode mode)
{
    int pair[2];
    pid_t writer;
    struct w3_request_frame frame;
    int status = 0;
    int baseline = open_fd_count();
    int receive_result;
    int receive_errno;
    int valid;

    if (socketpair(AF_UNIX, SOCK_STREAM, 0, pair) != 0) {
        return -1;
    }
    writer = fork();
    if (writer == 0) {
        (void)close(pair[0]);
        if (mode == TRUNCATED_BODY) {
            struct w3_launcher_request_header header;
            uint8_t one = 0x41;
            fill_request_header(&header, 2U);
            (void)write_fragmented(pair[1], (const uint8_t *)&header, sizeof(header), 23U);
            (void)write(pair[1], &one, 1U);
            (void)shutdown(pair[1], SHUT_WR);
        } else if (mode == STALLED_BODY) {
            struct w3_launcher_request_header header;
            uint8_t one = 0x41;
            fill_request_header(&header, 2U);
            (void)write_fragmented(pair[1], (const uint8_t *)&header, sizeof(header), 23U);
            (void)write(pair[1], &one, 1U);
            for (;;) {
                pause();
            }
        } else {
            bad_frame_writer(pair[1], mode);
        }
        (void)close(pair[1]);
        _exit(0);
    }
    (void)close(pair[1]);
    memset(&frame, 0, sizeof(frame));
    errno = 0;
    receive_result = writer < 0 ? 0 : w3_receive_request_frame(pair[0], &frame);
    receive_errno = errno;
    valid = writer >= 0 && receive_result != 0 &&
            (mode != STALLED_BODY || receive_errno == ETIMEDOUT);
    w3_free_request_frame(&frame);
    if (mode == STALLED_BODY && writer > 0) {
        (void)kill(writer, SIGKILL);
    }
    (void)close(pair[0]);
    if (writer < 0 || waitpid(writer, &status, 0) != writer ||
        (mode == STALLED_BODY ? !WIFSIGNALED(status) : !WIFEXITED(status)) ||
        open_fd_count() != baseline) {
        return -1;
    }
    return valid ? 0 : -1;
}

static int scenario_frame_invalid(void)
{
    int mode;
    for (mode = BAD_MAGIC; mode <= ANCILLARY_RIGHT; ++mode) {
        if (expect_bad_frame((enum bad_frame_mode)mode) != 0) {
            return 40 + mode;
        }
    }
    puts("frame-invalid-ok");
    return 0;
}

static int scenario_credentials_ok(void)
{
    reset_identity();
    test_regain_mode = 0;
    if (w3_drop_with_ops(&w3_system_credential_ops) != 0 ||
        strcmp(test_order, "abcde") != 0 || test_uid != W3_RUNNER_UID ||
        test_gid != W3_RUNNER_GID || test_group_count != 0) {
        return 50;
    }
    puts("credentials-ok");
    return 0;
}

static int scenario_credentials_bad(void)
{
    int mode;
    for (mode = 1; mode <= 6; ++mode) {
        reset_identity();
        test_regain_mode = mode;
        if (w3_drop_with_ops(&w3_system_credential_ops) == 0) {
            return 60 + mode;
        }
    }
    puts("credentials-bad-ok");
    return 0;
}

static int run_stub_payload_with_regain(
    int mode,
    int regain_mode,
    const uint8_t *payload,
    uint32_t payload_length,
    struct w3_execution_result *result
)
{
    reset_identity();
    test_regain_mode = regain_mode;
    test_exec_mode = mode;
    return w3_phase_b_launch_registered_node(
        payload,
        payload_length,
        W3_BROKER_UID,
        W3_BROKER_GID,
        result
    );
}

static int run_stub_with_regain(
    int mode,
    int regain_mode,
    struct w3_execution_result *result
)
{
    static const uint8_t payload[] = {'t', 'e', 's', 't'};

    return run_stub_payload_with_regain(
        mode,
        regain_mode,
        payload,
        sizeof(payload),
        result
    );
}

static int run_stub(int mode, struct w3_execution_result *result)
{
    return run_stub_with_regain(mode, 0, result);
}

static int exact_clean_result(const struct w3_execution_result *result)
{
    return result->process_group_residual == 0U && result->retained_fds == 0U &&
           result->temp_entries == 0U &&
           result->broker_peer_uid == W3_BROKER_UID &&
           result->broker_peer_gid == W3_BROKER_GID && result->launcher_uid == 0U &&
           result->launcher_gid == 0U && result->runner_uid == W3_RUNNER_UID &&
           result->runner_gid == W3_RUNNER_GID && result->child_boundary_succeeded == 1U &&
           (result->flags & W3_RESULT_PROCESS_GROUP_ZERO) != 0U &&
           (result->flags & W3_RESULT_FD_ZERO) != 0U &&
           (result->flags & W3_RESULT_TEMP_ZERO) != 0U;
}

static int scenario_boundary(void)
{
    struct w3_execution_result result;
    int valid;

    if (run_stub(0, &result) != 0) {
        (void)fprintf(stderr, "boundary setup errno=%d\n", errno);
        return 70;
    }
    valid = result.status == W3_LAUNCHER_STATUS_COMPLETE &&
            result.wait_kind == W3_WAIT_EXITED && result.wait_value == 0U &&
            result.stdout_length == 8U && result.stderr_length == 8U &&
            memcmp(result.stdout_bytes, "stub-out", 8U) == 0 &&
            memcmp(result.stderr_bytes, "stub-err", 8U) == 0 &&
            exact_clean_result(&result);
    w3_free_execution_result(&result);
    if (!valid) {
        return 71;
    }
    puts("boundary-ok");
    return 0;
}

static int scenario_policy_rejected(void)
{
    struct w3_execution_result result;

    if (run_stub(0, &result) == 0) {
        w3_free_execution_result(&result);
        return 72;
    }
    w3_free_execution_result(&result);
    puts("policy-rejected-ok");
    return 0;
}

static int scenario_pgid_identity_retained(void)
{
    int wait_status = 0;
    int reaped = 0;
    size_t pid_count = 0U;

    if (w3_pid_count_from_census_bytes(
            (int)(sizeof(pid_t) * 2U),
            sizeof(pid_t) * 4U,
            &pid_count
        ) != 0 ||
        pid_count != 2U ||
        w3_pid_count_from_census_bytes(
            (int)(sizeof(pid_t) + 1U),
            sizeof(pid_t) * 4U,
            &pid_count
        ) == 0 ||
        w3_pid_count_from_census_bytes(
            (int)(sizeof(pid_t) * 4U),
            sizeof(pid_t) * 4U,
            &pid_count
        ) == 0 ||
        w3_pid_count_from_census_bytes(0, sizeof(pid_t) * 4U, &pid_count) == 0) {
        return 73;
    }

    reset_pgid_ops(0U, 0);
    if (w3_terminate_and_reap_group_with(4242, &wait_status, &reaped, &fake_process_ops) != 0U ||
        !reaped || pgid_post_reap_operation || strcmp(pgid_order, "ocr") != 0) {
        return 74;
    }
    wait_status = 0;
    reaped = 0;
    reset_pgid_ops(1U, 0);
    if (w3_terminate_and_reap_group_with(4242, &wait_status, &reaped, &fake_process_ops) != 0U ||
        !reaped || pgid_post_reap_operation || strcmp(pgid_order, "octocr") != 0) {
        return 75;
    }
    wait_status = 0;
    reaped = 0;
    reset_pgid_ops(0U, 1);
    if (w3_terminate_and_reap_group_with(4242, &wait_status, &reaped, &fake_process_ops) == 0U ||
        reaped || pgid_post_reap_operation || strcmp(pgid_order, "ocr") != 0 ||
        errno != ECHILD) {
        return 76;
    }
    wait_status = 0;
    reaped = 0;
    reset_pgid_ops(0U, 0);
    pgid_leader_terminal = 0;
    if (w3_terminate_and_reap_pid_with(4242, &wait_status, &reaped, &fake_process_ops) != 0U ||
        !reaped || pgid_post_reap_operation || pgid_group_operation_count != 0 ||
        strcmp(pgid_order, "opor") != 0) {
        return 77;
    }
    puts("pgid-identity-ok");
    return 0;
}

static int scenario_run_anchor(void)
{
    struct w3_run_root_anchor anchor = {.parent_fd = -1, .leaf_fd = -1};
    const char *displaced = W3_RUN_PARENT "/displaced";
    int anchored_file = -1;
    int replacement_exists = 0;
    int displaced_exists = 0;
    int outcome = 79;

    if (w3_open_run_root_anchor(&anchor) != 0 ||
        rename(W3_RUN_ROOT, displaced) != 0) {
        goto cleanup;
    }
    displaced_exists = 1;
    if (mkdir(W3_RUN_ROOT, 0700) != 0) {
        goto cleanup;
    }
    replacement_exists = 1;
    anchored_file = openat(anchor.leaf_fd, "anchored", O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (anchored_file < 0 || w3_reverify_run_root_anchor(&anchor) == 0 ||
        w3_count_temp_entries_at(anchor.leaf_fd) != 1U) {
        goto cleanup;
    }
    outcome = 0;

cleanup:
    if (anchored_file >= 0) {
        (void)close(anchored_file);
        (void)unlinkat(anchor.leaf_fd, "anchored", 0);
    }
    if (replacement_exists) {
        (void)rmdir(W3_RUN_ROOT);
    }
    if (displaced_exists) {
        (void)rename(displaced, W3_RUN_ROOT);
    }
    if (outcome == 0 && w3_reverify_run_root_anchor(&anchor) != 0) {
        outcome = 80;
    }
    w3_close_run_root_anchor(&anchor);
    if (outcome == 0) {
        if (chmod(W3_RUN_ROOT, 0770) != 0 || w3_open_run_root_anchor(&anchor) == 0) {
            outcome = 81;
        }
        w3_close_run_root_anchor(&anchor);
        if (chmod(W3_RUN_ROOT, 0700) != 0 ||
            w3_open_run_root_anchor(&anchor) != 0) {
            outcome = 82;
        }
        w3_close_run_root_anchor(&anchor);
        if (outcome == 0 &&
            (chmod(W3_RUN_PARENT, 0700) != 0 ||
             w3_open_run_root_anchor(&anchor) == 0)) {
            outcome = 83;
        }
        w3_close_run_root_anchor(&anchor);
        if (chmod(W3_RUN_PARENT, 0711) != 0 ||
            w3_open_run_root_anchor(&anchor) != 0) {
            outcome = 84;
        }
        w3_close_run_root_anchor(&anchor);
    }
    if (outcome != 0) {
        return outcome;
    }
    puts("run-anchor-ok");
    return 0;
}

static int read_exact_plain(int descriptor, void *buffer, size_t length)
{
    uint8_t *cursor = buffer;
    size_t consumed = 0U;
    while (consumed < length) {
        ssize_t count = read(descriptor, cursor + consumed, length - consumed);
        if (count > 0) {
            consumed += (size_t)count;
        } else if (count < 0 && errno == EINTR) {
            continue;
        } else {
            return -1;
        }
    }
    return 0;
}

static int scenario_response(void)
{
    struct w3_execution_result result;
    struct w3_launcher_request_header request;
    struct w3_launcher_response_header response;
    struct w3_launcher_result_header inner;
    struct w3_launcher_cleanup_record cleanup;
    uint8_t computed[W3_SHA256_BYTES];
    uint8_t *payload;
    uint32_t length;
    uint32_t stdout_length;
    uint32_t stderr_length;
    int pair[2];
    int valid = 0;

    if (run_stub(0, &result) != 0 || socketpair(AF_UNIX, SOCK_STREAM, 0, pair) != 0) {
        return 80;
    }
    fill_request_header(&request, 4U);
    if (w3_send_execution_response(pair[0], &request, &result) != 0 ||
        read_exact_plain(pair[1], &response, sizeof(response)) != 0) {
        return 81;
    }
    length = ntohl(response.payload_length_be);
    payload = calloc(length, 1U);
    if (payload == NULL || read_exact_plain(pair[1], payload, length) != 0 ||
        length < sizeof(inner) + sizeof(cleanup)) {
        return 82;
    }
    memcpy(&inner, payload, sizeof(inner));
    stdout_length = ntohl(inner.stdout_length_be);
    stderr_length = ntohl(inner.stderr_length_be);
    memcpy(&cleanup, payload + sizeof(inner) + stdout_length + stderr_length, sizeof(cleanup));
    (void)CC_SHA256(&cleanup, (CC_LONG)sizeof(cleanup), computed);
    valid = memcmp(response.magic, W3_LAUNCHER_MAGIC, W3_LAUNCHER_MAGIC_BYTES) == 0 &&
            ntohl(response.version_be) == 1U && ntohl(response.status_be) == 0U &&
            memcmp(response.request_sha256, request.request_sha256, W3_SHA256_BYTES) == 0 &&
            memcmp(response.broker_nonce, request.broker_nonce, W3_NONCE_BYTES) == 0 &&
            memcmp(response.cleanup_sha256, computed, sizeof(computed)) == 0 &&
            memcmp(inner.magic, W3_LAUNCHER_RESULT_MAGIC, W3_LAUNCHER_MAGIC_BYTES) == 0 &&
            ntohl(inner.version_be) == 1U && stdout_length == 8U && stderr_length == 8U &&
            ntohl(inner.cleanup_length_be) == sizeof(cleanup) &&
            memcmp(cleanup.magic, W3_LAUNCHER_CLEANUP_MAGIC, W3_LAUNCHER_MAGIC_BYTES) == 0 &&
            ntohl(cleanup.broker_peer_uid_be) == W3_BROKER_UID &&
            ntohl(cleanup.broker_peer_gid_be) == W3_BROKER_GID &&
            ntohl(cleanup.launcher_uid_be) == 0U && ntohl(cleanup.launcher_gid_be) == 0U &&
            ntohl(cleanup.runner_uid_be) == W3_RUNNER_UID &&
            ntohl(cleanup.runner_gid_be) == W3_RUNNER_GID &&
            ntohl(cleanup.child_boundary_succeeded_be) == 1U &&
            exact_clean_result(&result);
    free(payload);
    (void)close(pair[0]);
    (void)close(pair[1]);
    w3_free_execution_result(&result);
    if (!valid) {
        return 83;
    }
    puts("response-ok");
    return 0;
}

static int scenario_failures(void)
{
    struct w3_execution_result drop_result;
    struct w3_execution_result timeout_result;
    struct w3_execution_result cap_result;
    struct w3_execution_result early_close_result;
    struct w3_launcher_request_header request;
    struct sigaction default_pipe;
    uint8_t *large_payload;
    int pair[2];
    int valid;

    if (run_stub_with_regain(0, 1, &drop_result) != 0 ||
        drop_result.status != W3_LAUNCHER_STATUS_LAUNCH_FAILED ||
        drop_result.child_boundary_succeeded != 0U ||
        drop_result.process_group_residual != 0U || drop_result.retained_fds != 0U ||
        drop_result.temp_entries != 0U) {
        (void)fprintf(
            stderr,
            "drop status=%u boundary=%u pg=%u fds=%u temp=%u flags=%u wait=%u/%u\n",
            drop_result.status,
            drop_result.child_boundary_succeeded,
            drop_result.process_group_residual,
            drop_result.retained_fds,
            drop_result.temp_entries,
            drop_result.flags,
            drop_result.wait_kind,
            drop_result.wait_value
        );
        return 89;
    }
    w3_free_execution_result(&drop_result);
    if (run_stub(1, &timeout_result) != 0 ||
        timeout_result.status != W3_LAUNCHER_STATUS_TIMED_OUT ||
        (timeout_result.flags & W3_RESULT_TIMED_OUT) == 0U ||
        !exact_clean_result(&timeout_result)) {
        return 90;
    }
    if (run_stub(2, &cap_result) != 0 ||
        cap_result.status != W3_LAUNCHER_STATUS_OUTPUT_CAPPED ||
        (cap_result.flags & W3_RESULT_OUTPUT_CAPPED) == 0U ||
        !exact_clean_result(&cap_result)) {
        (void)fprintf(
            stderr,
            "cap status=%u boundary=%u pg=%u fds=%u temp=%u flags=%u wait=%u/%u out=%u\n",
            cap_result.status,
            cap_result.child_boundary_succeeded,
            cap_result.process_group_residual,
            cap_result.retained_fds,
            cap_result.temp_entries,
            cap_result.flags,
            cap_result.wait_kind,
            cap_result.wait_value,
            cap_result.stdout_length
        );
        return 91;
    }
    large_payload = calloc(W3_LAUNCHER_MAX_PAYLOAD_BYTES, 1U);
    memset(&default_pipe, 0, sizeof(default_pipe));
    default_pipe.sa_handler = SIG_DFL;
    if (large_payload == NULL || sigemptyset(&default_pipe.sa_mask) != 0 ||
        sigaction(SIGPIPE, &default_pipe, NULL) != 0) {
        free(large_payload);
        return 94;
    }
    valid = run_stub_payload_with_regain(
                3,
                0,
                large_payload,
                W3_LAUNCHER_MAX_PAYLOAD_BYTES,
                &early_close_result
            ) == 0 &&
            early_close_result.status == W3_LAUNCHER_STATUS_COMPLETE &&
            early_close_result.wait_kind == W3_WAIT_EXITED &&
            early_close_result.wait_value == 0U &&
            exact_clean_result(&early_close_result);
    free(large_payload);
    w3_free_execution_result(&early_close_result);
    if (!valid) {
        return 95;
    }
    fill_request_header(&request, 4U);
    if (socketpair(AF_UNIX, SOCK_STREAM, 0, pair) != 0) {
        return 92;
    }
    (void)close(pair[1]);
    valid = w3_send_execution_response(pair[0], &request, &cap_result) != 0 &&
            (errno == EPIPE || errno == ECONNRESET);
    (void)close(pair[0]);
    w3_free_execution_result(&timeout_result);
    w3_free_execution_result(&cap_result);
    if (!valid) {
        return 93;
    }
    puts("failures-ok");
    return 0;
}

int main(int argc, char **argv)
{
    if (argc < 2) {
        return 2;
    }
    if (strcmp(argv[1], "activation") == 0 && argc == 3) {
        return scenario_activation(argv[2]);
    }
    if (strcmp(argv[1], "peer") == 0) {
        return scenario_peer();
    }
    if (strcmp(argv[1], "frame-valid") == 0) {
        return scenario_frame_valid();
    }
    if (strcmp(argv[1], "frame-invalid") == 0) {
        return scenario_frame_invalid();
    }
    if (strcmp(argv[1], "credentials-ok") == 0) {
        return scenario_credentials_ok();
    }
    if (strcmp(argv[1], "credentials-bad") == 0) {
        return scenario_credentials_bad();
    }
    if (strcmp(argv[1], "boundary") == 0) {
        return scenario_boundary();
    }
    if (strcmp(argv[1], "policy-rejected") == 0) {
        return scenario_policy_rejected();
    }
    if (strcmp(argv[1], "pgid-identity") == 0) {
        return scenario_pgid_identity_retained();
    }
    if (strcmp(argv[1], "run-anchor") == 0) {
        return scenario_run_anchor();
    }
    if (strcmp(argv[1], "response") == 0) {
        return scenario_response();
    }
    if (strcmp(argv[1], "failures") == 0) {
        return scenario_failures();
    }
    return 3;
}
"""


SHIM_HARNESS = r"""
#define main w3_shim_product_main
#include "__SHIM_SOURCE__"
#undef main

static int shim_listener = -1;
static size_t shim_count = 1U;

static int create_shim_listener(const char *path)
{
    struct sockaddr_un address;
    int descriptor = socket(AF_UNIX, SOCK_STREAM, 0);
    if (descriptor < 0 || strlen(path) >= sizeof(address.sun_path)) {
        return -1;
    }
    memset(&address, 0, sizeof(address));
    address.sun_family = AF_UNIX;
    (void)strncpy(address.sun_path, path, sizeof(address.sun_path) - 1U);
    (void)unlink(path);
    if (bind(descriptor, (struct sockaddr *)&address, sizeof(address)) != 0 ||
        listen(descriptor, 4) != 0) {
        return -1;
    }
    return descriptor;
}

static int fake_shim_activate(const char *name, int **descriptors, size_t *count)
{
    size_t index;
    if (strcmp(name, W3_SHIM_LISTENER_NAME) != 0) {
        return ENOENT;
    }
    *count = shim_count;
    *descriptors = shim_count == 0U ? NULL : calloc(shim_count, sizeof(int));
    if (shim_count != 0U && *descriptors == NULL) {
        return ENOMEM;
    }
    for (index = 0U; index < shim_count; ++index) {
        (*descriptors)[index] = dup(shim_listener);
    }
    return 0;
}

static int fake_shim_execve(const char *path, char *const argv[], char *const environment[])
{
    static const char *const expected_environment[] = {
        "HOME=/var/empty", "LANG=C", "LC_ALL=C", "PATH=/usr/bin:/bin", "TZ=UTC", NULL,
    };
    char cwd[8];
    int descriptor;
    size_t index;
    int socket_type = 0;
    socklen_t length = sizeof(socket_type);

    if (strcmp(path, W3_SHIM_PYTHON_PATH) != 0 || argv[0] == NULL ||
        strcmp(argv[0], W3_SHIM_PYTHON_PATH) != 0 || argv[1] == NULL ||
        strcmp(argv[1], "-I") != 0 || argv[2] == NULL || strcmp(argv[2], "-B") != 0 ||
        argv[3] == NULL || strcmp(argv[3], "-m") != 0 || argv[4] == NULL ||
        strcmp(argv[4], W3_SHIM_MODULE_NAME) != 0 || argv[5] != NULL ||
        getcwd(cwd, sizeof(cwd)) == NULL || strcmp(cwd, "/") != 0 ||
        getsockopt(3, SOL_SOCKET, SO_TYPE, &socket_type, &length) != 0 ||
        socket_type != SOCK_STREAM) {
        _exit(20);
    }
    for (index = 0U; expected_environment[index] != NULL; ++index) {
        if (environment[index] == NULL ||
            strcmp(environment[index], expected_environment[index]) != 0) {
            _exit(21);
        }
    }
    if (environment[index] != NULL) {
        _exit(22);
    }
    for (descriptor = 4; descriptor < 64; ++descriptor) {
        errno = 0;
        if (fcntl(descriptor, F_GETFD) >= 0 || errno != EBADF) {
            _exit(23);
        }
    }
    (void)write(STDOUT_FILENO, "shim-ok\n", 8U);
    _exit(0);
}

int main(int argc, char **argv)
{
    int decoy;
    if (argc != 2) {
        return 2;
    }
    decoy = open("/dev/null", O_RDONLY);
    shim_listener = create_shim_listener(argv[1]);
    if (decoy < 0 || shim_listener < 0) {
        return 3;
    }
    shim_count = 0U;
    if (w3_shim_run_with(fake_shim_activate, fake_shim_execve) != EX_UNAVAILABLE) {
        return 4;
    }
    shim_count = 2U;
    if (w3_shim_run_with(fake_shim_activate, fake_shim_execve) != EX_UNAVAILABLE) {
        return 5;
    }
    shim_count = 1U;
    return w3_shim_run_with(fake_shim_activate, fake_shim_execve);
}
"""


def _compile(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True)


@pytest.fixture(scope="session")
def native_harnesses(tmp_path_factory: pytest.TempPathFactory) -> NativeHarnesses:
    build = tmp_path_factory.mktemp("w3-native-harness")
    run_parent = build / "runs"
    run_parent.mkdir(mode=0o711)
    run_root = run_parent / "active"
    run_root.mkdir(mode=0o700)
    seatbelt_policy = build / "w3-runner.sb"
    policy_bytes = SEATBELT_POLICY.read_bytes().replace(
        b"/Library/Application Support/MetisModel1/runs/active",
        run_root.as_posix().encode("utf-8"),
    )
    seatbelt_policy.write_bytes(policy_bytes)
    seatbelt_policy.chmod(0o444)
    policy_sha256 = hashlib.sha256(policy_bytes).hexdigest()
    launcher_c = build / "launcher_harness.c"
    launcher_c.write_text(
        LAUNCHER_HARNESS.replace("__LAUNCHER_SOURCE__", LAUNCHER_SOURCE.as_posix()),
        encoding="utf-8",
    )
    launcher = build / "launcher-harness"
    launcher_socket = _socket_path("launcher")
    common = [
        "/usr/bin/clang",
        "-std=c17",
        "-Wall",
        "-Wextra",
        "-Wpedantic",
        "-Werror",
        "-O1",
    ]
    _compile(
        [
            *common,
            "-DW3_PRIVILEGED_LAUNCHER_PHASE_B=1",
            f"-DW3_BROKER_UID={os.getuid()}",
            f"-DW3_BROKER_GID={os.getgid()}",
            "-DW3_RUNNER_UID=59998",
            "-DW3_RUNNER_GID=59998",
            f'-DW3_LAUNCHER_SOCKET_PATH="{launcher_socket.as_posix()}"',
            f'-DW3_SEATBELT_POLICY_PATH="{seatbelt_policy.as_posix()}"',
            f'-DW3_SEATBELT_POLICY_SHA256="{policy_sha256}"',
            f"-DW3_SEATBELT_POLICY_UID={os.getuid()}",
            f"-DW3_SEATBELT_POLICY_GID={os.getgid()}",
            "-DW3_LOCAL_SIMULATION=1",
            f'-DW3_RUN_PARENT="{run_parent.as_posix()}"',
            f"-DW3_RUN_PARENT_UID={os.getuid()}",
            f"-DW3_RUN_PARENT_GID={os.getgid()}",
            f"-DW3_RUN_LEAF_UID={os.getuid()}",
            f"-DW3_RUN_LEAF_GID={os.getgid()}",
            "-DW3_FRAME_TIMEOUT_MS=500U",
            "-DW3_EXECUTION_TIMEOUT_MS=500U",
            "-DW3_TERM_GRACE_MS=30U",
            "-DW3_MAX_STDOUT_BYTES=128U",
            "-DW3_MAX_STDERR_BYTES=64U",
            str(launcher_c),
            "-o",
            str(launcher),
        ]
    )

    shim_c = build / "shim_harness.c"
    shim_c.write_text(
        SHIM_HARNESS.replace("__SHIM_SOURCE__", SHIM_SOURCE.as_posix()),
        encoding="utf-8",
    )
    broker_shim = build / "broker-shim-harness"
    anchor_shim = build / "anchor-shim-harness"
    _compile(
        [
            *common,
            '-DW3_SHIM_LISTENER_NAME="BrokerListener"',
            '-DW3_SHIM_MODULE_NAME="runtime.w3_broker_service"',
            str(shim_c),
            "-o",
            str(broker_shim),
        ]
    )
    _compile(
        [
            *common,
            '-DW3_SHIM_LISTENER_NAME="AnchorListener"',
            '-DW3_SHIM_MODULE_NAME="runtime.w3_anchor_service"',
            str(shim_c),
            "-o",
            str(anchor_shim),
        ]
    )
    return NativeHarnesses(
        launcher=launcher,
        launcher_socket=launcher_socket,
        seatbelt_policy=seatbelt_policy,
        broker_shim=broker_shim,
        anchor_shim=anchor_shim,
    )


def _socket_path(label: str) -> Path:
    return Path("/tmp") / f"metis-l70-{label}-{uuid.uuid4().hex[:12]}.sock"


def _run(harness: Path, *arguments: str, expected: str) -> None:
    completed = subprocess.run(
        [str(harness), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == f"{expected}\n"


def test_launchd_activation_is_exactly_one_named_unix_listener(
    native_harnesses: NativeHarnesses,
) -> None:
    socket_path = native_harnesses.launcher_socket
    try:
        _run(
            native_harnesses.launcher,
            "activation",
            str(socket_path),
            expected="activation-ok",
        )
    finally:
        socket_path.unlink(missing_ok=True)
    source = LAUNCHER_SOURCE.read_text(encoding="utf-8")
    assert 'activate_fn("LauncherListener"' in source
    assert '#define W3_LAUNCHER_SOCKET_PATH "/var/run/metis-model1/w3-launcher.sock"' in source
    assert "address_length != (socklen_t)expected_address_length" in source
    assert "bind(" not in source and "unlink(" not in source


def test_fixed_target_shims_map_broker_and_anchor_listener_to_fd3(
    native_harnesses: NativeHarnesses,
) -> None:
    shim_source = SHIM_SOURCE.read_text(encoding="utf-8")
    installer_source = INSTALLER_SOURCE.read_text(encoding="utf-8")
    assert '"/Library/Application Support/MetisModel1/runtime/python/bin/python3.13"' in shim_source
    assert '"-I"' in shim_source and '"-B"' in shim_source and '"-m"' in shim_source
    assert '"runtime.w3_broker_service"' in shim_source
    assert '"runtime.w3_anchor_service"' in shim_source
    assert "W3_SHIM_TARGET_PATH" not in shim_source
    assert 'PYTHON_ROOT = f"{APP_SUPPORT_ROOT}/runtime/python"' in installer_source
    for module in ("runtime.w3_broker_service", "runtime.w3_anchor_service"):
        assert module.replace(".", "/") + ".py" in installer_source
    assert '"broker-socket-shim"' in installer_source
    assert '"anchor-socket-shim"' in installer_source
    plist = plistlib.loads(LAUNCHER_PLIST.read_bytes())
    assert list(plist["Sockets"]) == ["LauncherListener"]
    assert plist["Sockets"]["LauncherListener"] == {
        "SockPathName": "/var/run/metis-model1/w3-launcher.sock",
        "SockPathOwner": 499,
        "SockPathGroup": 499,
        "SockPathMode": 0o600,
    }
    for label, harness in (
        ("broker", native_harnesses.broker_shim),
        ("anchor", native_harnesses.anchor_shim),
    ):
        socket_path = _socket_path(label)
        try:
            _run(harness, str(socket_path), expected="shim-ok")
        finally:
            socket_path.unlink(missing_ok=True)


def test_original_connection_requires_exact_peer_uid_and_gid(
    native_harnesses: NativeHarnesses,
) -> None:
    _run(native_harnesses.launcher, "peer", expected="peer-ok")
    source = LAUNCHER_SOURCE.read_text(encoding="utf-8")
    peer_at = source.index("w3_authorize_broker_peer(descriptor, &broker_peer_uid")
    frame_at = source.index("w3_receive_request_frame(descriptor")
    assert peer_at < frame_at


def test_fragmented_frame_accepts_exact_four_mib_and_write_eof(
    native_harnesses: NativeHarnesses,
) -> None:
    _run(native_harnesses.launcher, "frame-valid", expected="frame-valid-ok")


def test_frame_mutations_trailing_and_ancillary_rights_fail_closed(
    native_harnesses: NativeHarnesses,
) -> None:
    _run(native_harnesses.launcher, "frame-invalid", expected="frame-invalid-ok")


def test_credential_drop_order_and_both_regain_denials_are_exact(
    native_harnesses: NativeHarnesses,
) -> None:
    _run(native_harnesses.launcher, "credentials-ok", expected="credentials-ok")
    source = LAUNCHER_SOURCE.read_text(encoding="utf-8")
    function = source.split("static int w3_drop_irreversibly_to_runner", 1)[1]
    assert function.index("setgroups(0, NULL)") < function.index("setgid(W3_RUNNER_GID)")
    assert function.index("setgid(W3_RUNNER_GID)") < function.index("setuid(W3_RUNNER_UID)")
    assert function.index("setuid(W3_RUNNER_UID)") < function.index("setuid(0)")
    assert function.index("setuid(0)") < function.index("setgid(0)")


def test_any_successful_or_non_eperm_regain_attempt_aborts(
    native_harnesses: NativeHarnesses,
) -> None:
    _run(native_harnesses.launcher, "credentials-bad", expected="credentials-bad-ok")


def test_child_has_only_stdio_and_fixed_sandbox_argv_and_environment(
    native_harnesses: NativeHarnesses,
) -> None:
    _run(native_harnesses.launcher, "boundary", expected="boundary-ok")
    policy_bytes = native_harnesses.seatbelt_policy.read_bytes()
    assert b"(param" not in policy_bytes
    assert hashlib.sha256(SEATBELT_POLICY.read_bytes()).hexdigest() in LAUNCHER_SOURCE.read_text(
        encoding="utf-8"
    )
    try:
        native_harnesses.seatbelt_policy.chmod(0o644)
        _run(
            native_harnesses.launcher,
            "policy-rejected",
            expected="policy-rejected-ok",
        )
        native_harnesses.seatbelt_policy.write_bytes(policy_bytes + b'\n(param "UNBOUND_PATH")\n')
        native_harnesses.seatbelt_policy.chmod(0o444)
        _run(
            native_harnesses.launcher,
            "policy-rejected",
            expected="policy-rejected-ok",
        )
    finally:
        native_harnesses.seatbelt_policy.chmod(0o644)
        native_harnesses.seatbelt_policy.write_bytes(policy_bytes)
        native_harnesses.seatbelt_policy.chmod(0o444)
    launcher = LAUNCHER_SOURCE.read_text(encoding="utf-8")
    runner = RUNNER_SOURCE.read_text(encoding="utf-8")
    required_flags = set(re.findall(r"argument\(argv, '(--[^']+)'\)", runner))
    assert len(required_flags) == 20
    assert all(launcher.count(f'"{flag}"') == 1 for flag in required_flags)
    assert '"--disable-warning=ExperimentalWarning"' in launcher
    assert '"--experimental-loader"' in launcher
    assert '"--import"' not in launcher
    assert "w3_validate_seatbelt_policy() != 0" in launcher
    assert 'w3_policy_contains_bytes(bytes, length, "(param")' in launcher
    assert "O_RDONLY | O_NOFOLLOW | O_CLOEXEC" in launcher
    assert "w3_production_worker" not in launcher


def test_pgid_reap_caps_cleanup_and_binary_response_are_cross_bound(
    native_harnesses: NativeHarnesses,
) -> None:
    _run(native_harnesses.launcher, "pgid-identity", expected="pgid-identity-ok")
    _run(native_harnesses.launcher, "run-anchor", expected="run-anchor-ok")
    _run(native_harnesses.launcher, "response", expected="response-ok")


def test_timeout_cap_and_disconnected_response_never_emit_green(
    native_harnesses: NativeHarnesses,
) -> None:
    _run(native_harnesses.launcher, "failures", expected="failures-ok")
