/*
 * Model 1 W3 privileged launcher.
 *
 * L70 makes this source installable but does not give a repository-built
 * binary any authority. An accepted Phase-B installer must compile and place
 * the binary below root-owned immutable ancestry with every W3_* identity and
 * path frozen. Local tests replace credential and exec syscalls and run only
 * native public stubs; they are simulation, never host evidence.
 *
 * The launcher obtains exactly one launchd-owned Unix listener, authenticates
 * the original _metisbroker connection by UID and GID, receives one bounded
 * binary frame, supervises one fixed sandbox-exec/Node argv after irreversible
 * drop to _metisrunner, and returns a fixed binary result on the same socket.
 * It never parses JSON, selects caller paths/argv/environment, owns a signing
 * key, registers authority, binds or unlinks a socket, or runs as Node.
 */

#include <arpa/inet.h>
#include <CommonCrypto/CommonDigest.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <launch.h>
#include <libproc.h>
#include <poll.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sysexits.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define W3_LAUNCHER_MAGIC "M1W3LCH"
#define W3_LAUNCHER_RESULT_MAGIC "M1W3RES"
#define W3_LAUNCHER_CLEANUP_MAGIC "M1W3CLN"
#define W3_LAUNCHER_MAGIC_BYTES 8U
#define W3_LAUNCHER_PROTOCOL_VERSION 1U
#define W3_LAUNCHER_RESULT_VERSION 1U
#define W3_LAUNCHER_CLEANUP_VERSION 1U
#define W3_LAUNCHER_MAX_PAYLOAD_BYTES (4U * 1024U * 1024U)
#define W3_SHA256_BYTES 32U
#define W3_NONCE_BYTES 32U
#define W3_MAX_ANCILLARY_FDS 16U
#define W3_ANCILLARY_RIGHTS_TYPE 0x01
#define W3_IO_CHUNK_BYTES 16384U
#define W3_MAX_SEATBELT_POLICY_BYTES (64U * 1024U)
#define W3_MAX_PROCESS_GROUP_PIDS 4096U

#ifndef W3_LAUNCHER_SOCKET_PATH
#define W3_LAUNCHER_SOCKET_PATH "/var/run/metis-model1/w3-launcher.sock"
#endif

#ifndef W3_FRAME_TIMEOUT_MS
#define W3_FRAME_TIMEOUT_MS 5000U
#endif

#ifndef W3_EXECUTION_TIMEOUT_MS
#define W3_EXECUTION_TIMEOUT_MS 120000U
#endif

#ifndef W3_TERM_GRACE_MS
#define W3_TERM_GRACE_MS 1000U
#endif

#ifndef W3_MAX_STDOUT_BYTES
#define W3_MAX_STDOUT_BYTES (3U * 1024U * 1024U)
#endif

#ifndef W3_MAX_STDERR_BYTES
#define W3_MAX_STDERR_BYTES (1024U * 1024U - 4096U)
#endif

#ifndef W3_BROKER_UID
#define W3_BROKER_UID ((uid_t)-1)
#endif

#ifndef W3_BROKER_GID
#define W3_BROKER_GID ((gid_t)-1)
#endif

#ifndef W3_RUNNER_UID
#define W3_RUNNER_UID ((uid_t)-1)
#endif

#ifndef W3_RUNNER_GID
#define W3_RUNNER_GID ((gid_t)-1)
#endif

#ifndef W3_RELEASE_ROOT
#define W3_RELEASE_ROOT "/Library/Application Support/MetisModel1/releases/w3-public-synthetic-v1"
#endif

#ifndef W3_SANDBOX_EXEC_PATH
#define W3_SANDBOX_EXEC_PATH "/usr/bin/sandbox-exec"
#endif

#ifndef W3_SEATBELT_POLICY_PATH
#define W3_SEATBELT_POLICY_PATH W3_RELEASE_ROOT "/policy/w3-runner.sb"
#endif

#ifndef W3_SEATBELT_POLICY_SHA256
#define W3_SEATBELT_POLICY_SHA256 \
    "8fb0a554738e379076a213eeb8de2be91beff4d09943875dc6d7f58fc072f124"
#endif

#ifndef W3_SEATBELT_POLICY_UID
#define W3_SEATBELT_POLICY_UID ((uid_t)0)
#endif

#ifndef W3_SEATBELT_POLICY_GID
#define W3_SEATBELT_POLICY_GID ((gid_t)0)
#endif

#ifndef W3_SEATBELT_POLICY_MODE
#define W3_SEATBELT_POLICY_MODE ((mode_t)0444)
#endif

#ifndef W3_NODE_PATH
#define W3_NODE_PATH W3_RELEASE_ROOT "/runtime/node"
#endif

#ifndef W3_METIS_ROOT
#define W3_METIS_ROOT W3_RELEASE_ROOT "/capsule"
#endif

#ifndef W3_LOADER_PATH
#define W3_LOADER_PATH W3_RELEASE_ROOT "/capsule/.metis-oracle/native_ts_loader.mjs"
#endif

#ifndef W3_RUNNER_PATH
#define W3_RUNNER_PATH W3_RELEASE_ROOT "/capsule/.metis-oracle/runner.ts"
#endif

#ifndef W3_METIS_REVISION
#define W3_METIS_REVISION "a2dde2b191f6b78c2003d74875560da782470968"
#endif

#ifndef W3_METIS_TREE
#define W3_METIS_TREE "75473e26deff4084a0eb077a4c3e27d52dc07998"
#endif

#ifndef W3_TOOLING_PACKAGE_SHA256
#define W3_TOOLING_PACKAGE_SHA256 "f8130a67f948720b339695fae614f32185610f762d69b85ff600f08971f2fb80"
#endif

#ifndef W3_TOOLING_LOCK_SHA256
#define W3_TOOLING_LOCK_SHA256 "fed109b62f300ed824201f4b167d700072008b0b4a817cbb512a2eee32edc9fb"
#endif

#ifndef W3_NODE_MODULES_SHA256
#define W3_NODE_MODULES_SHA256 "1cea5f2f0371d3c57b9ef9787707bc1079f88dc697c7be2c6c247e4018f6e463"
#endif

#ifndef W3_RUNNER_SHA256
#define W3_RUNNER_SHA256 "772baa27e981f611681330bc463aef2ebe06b5f4a83ef2a0313ccf66b6dfef5d"
#endif

#ifndef W3_LOADER_SHA256
#define W3_LOADER_SHA256 "45e3557ce7ee345e2bca7de603c2ef8bc21aa2adb3f305d3f1cf6ee445273fee"
#endif

#ifndef W3_NODE_BINARY_SHA256
#define W3_NODE_BINARY_SHA256 "5d9d3872911e2340a43b707962e68143de8a4e8d54628845c0c4f2de1fb7cd5c"
#endif

#ifndef W3_ORACLE_POLICY_VERSION
#define W3_ORACLE_POLICY_VERSION "2"
#endif

#ifndef W3_ORACLE_POLICY_SHA256
#define W3_ORACLE_POLICY_SHA256 "deb8f45c9dfc2f336dbfb6f69a13e599a51929864ede8229969fa7f6e03f40aa"
#endif

#ifndef W3_EXECUTION_POLICY_SHA256
#define W3_EXECUTION_POLICY_SHA256 "4f29bf5e092d83993f19ad3d257cafd968a69b708679cecf5edc03cdf018de51"
#endif

#ifndef W3_RUNTIME_NODE_IDENTITY
#define W3_RUNTIME_NODE_IDENTITY "node://v22.22.3"
#endif

#ifndef W3_RUNTIME_LOADER_IDENTITY
#define W3_RUNTIME_LOADER_IDENTITY \
    "snapshot://" W3_METIS_REVISION "/" W3_METIS_TREE "/.metis-oracle/native_ts_loader.mjs"
#endif

#ifndef W3_RUNTIME_RUNNER_IDENTITY
#define W3_RUNTIME_RUNNER_IDENTITY \
    "snapshot://" W3_METIS_REVISION "/" W3_METIS_TREE "/.metis-oracle/runner.ts"
#endif

#ifndef W3_SNAPSHOT_IDENTITY
#define W3_SNAPSHOT_IDENTITY "snapshot://" W3_METIS_REVISION "/" W3_METIS_TREE
#endif

#ifndef W3_RUNTIME_LOADER_FLAGS_JSON
#define W3_RUNTIME_LOADER_FLAGS_JSON \
    "[\"--disable-warning=ExperimentalWarning\",\"--experimental-loader\"]"
#endif

#ifndef W3_RUN_PARENT
#define W3_RUN_PARENT "/Library/Application Support/MetisModel1/runs"
#endif

#ifndef W3_RUN_LEAF_NAME
#define W3_RUN_LEAF_NAME "active"
#endif

#define W3_RUN_ROOT W3_RUN_PARENT "/" W3_RUN_LEAF_NAME

#ifndef W3_RUN_PARENT_UID
#define W3_RUN_PARENT_UID ((uid_t)0)
#endif

#ifndef W3_RUN_PARENT_GID
#define W3_RUN_PARENT_GID ((gid_t)0)
#endif

#ifndef W3_RUN_LEAF_UID
#define W3_RUN_LEAF_UID W3_RUNNER_UID
#endif

#ifndef W3_RUN_LEAF_GID
#define W3_RUN_LEAF_GID W3_RUNNER_GID
#endif

enum w3_launcher_status {
    W3_LAUNCHER_STATUS_COMPLETE = 0,
    W3_LAUNCHER_STATUS_LAUNCH_FAILED = 1,
    W3_LAUNCHER_STATUS_TIMED_OUT = 2,
    W3_LAUNCHER_STATUS_OUTPUT_CAPPED = 3,
    W3_LAUNCHER_STATUS_IO_FAILED = 4,
    W3_LAUNCHER_STATUS_CLEANUP_FAILED = 5,
};

enum w3_wait_kind {
    W3_WAIT_UNAVAILABLE = 0,
    W3_WAIT_EXITED = 1,
    W3_WAIT_SIGNALED = 2,
};

enum w3_result_flags {
    W3_RESULT_EXITED = 1U << 0,
    W3_RESULT_SIGNALED = 1U << 1,
    W3_RESULT_TIMED_OUT = 1U << 2,
    W3_RESULT_OUTPUT_CAPPED = 1U << 3,
    W3_RESULT_PROCESS_GROUP_ZERO = 1U << 4,
    W3_RESULT_FD_ZERO = 1U << 5,
    W3_RESULT_TEMP_ZERO = 1U << 6,
};

struct w3_launcher_request_header {
    uint8_t magic[W3_LAUNCHER_MAGIC_BYTES];
    uint32_t version_be;
    uint32_t payload_length_be;
    uint8_t request_sha256[W3_SHA256_BYTES];
    uint8_t authority_sha256[W3_SHA256_BYTES];
    uint8_t release_sha256[W3_SHA256_BYTES];
    uint8_t broker_nonce[W3_NONCE_BYTES];
};

struct w3_launcher_response_header {
    uint8_t magic[W3_LAUNCHER_MAGIC_BYTES];
    uint32_t version_be;
    uint32_t status_be;
    uint32_t payload_length_be;
    uint8_t request_sha256[W3_SHA256_BYTES];
    uint8_t broker_nonce[W3_NONCE_BYTES];
    uint8_t cleanup_sha256[W3_SHA256_BYTES];
};

/* The outer protocol payload is opaque to w3_broker_protocol.py. */
struct w3_launcher_result_header {
    uint8_t magic[W3_LAUNCHER_MAGIC_BYTES];
    uint32_t version_be;
    uint32_t flags_be;
    uint32_t wait_kind_be;
    uint32_t wait_value_be;
    uint32_t stdout_length_be;
    uint32_t stderr_length_be;
    uint32_t cleanup_length_be;
};

struct w3_launcher_cleanup_record {
    uint8_t magic[W3_LAUNCHER_MAGIC_BYTES];
    uint32_t version_be;
    uint32_t flags_be;
    uint32_t process_group_residual_be;
    uint32_t retained_fds_be;
    uint32_t temp_entries_be;
    uint32_t wait_kind_be;
    uint32_t wait_value_be;
    uint32_t stdout_length_be;
    uint32_t stderr_length_be;
    uint32_t broker_peer_uid_be;
    uint32_t broker_peer_gid_be;
    uint32_t launcher_uid_be;
    uint32_t launcher_gid_be;
    uint32_t runner_uid_be;
    uint32_t runner_gid_be;
    uint32_t child_boundary_succeeded_be;
};

_Static_assert(sizeof(struct w3_launcher_request_header) == 144U, "request wire drift");
_Static_assert(sizeof(struct w3_launcher_response_header) == 116U, "response wire drift");
_Static_assert(sizeof(struct w3_launcher_result_header) == 36U, "result wire drift");
_Static_assert(sizeof(struct w3_launcher_cleanup_record) == 72U, "cleanup wire drift");
_Static_assert(sizeof(uid_t) <= sizeof(uint32_t), "uid wire width unsupported");
_Static_assert(sizeof(gid_t) <= sizeof(uint32_t), "gid wire width unsupported");
_Static_assert(
    sizeof(struct w3_launcher_result_header) + W3_MAX_STDOUT_BYTES +
            W3_MAX_STDERR_BYTES + sizeof(struct w3_launcher_cleanup_record) <=
        W3_LAUNCHER_MAX_PAYLOAD_BYTES,
    "configured output caps exceed the outer frame"
);

struct w3_request_frame {
    struct w3_launcher_request_header header;
    uint8_t *payload;
    uint32_t payload_length;
};

struct w3_execution_result {
    uint32_t status;
    uint32_t flags;
    uint32_t wait_kind;
    uint32_t wait_value;
    uint32_t process_group_residual;
    uint32_t retained_fds;
    uint32_t temp_entries;
    uint8_t *stdout_bytes;
    uint32_t stdout_length;
    uint8_t *stderr_bytes;
    uint32_t stderr_length;
    uint32_t broker_peer_uid;
    uint32_t broker_peer_gid;
    uint32_t launcher_uid;
    uint32_t launcher_gid;
    uint32_t runner_uid;
    uint32_t runner_gid;
    uint32_t child_boundary_succeeded;
    struct w3_launcher_cleanup_record cleanup;
};

struct w3_run_root_anchor {
    int parent_fd;
    int leaf_fd;
    struct stat parent_identity;
    struct stat leaf_identity;
};

struct w3_credential_ops {
    int (*setgroups_fn)(int, const gid_t *);
    int (*setgid_fn)(gid_t);
    int (*setuid_fn)(uid_t);
    int (*getgroups_fn)(int, gid_t *);
    gid_t (*getgid_fn)(void);
    gid_t (*getegid_fn)(void);
    uid_t (*getuid_fn)(void);
    uid_t (*geteuid_fn)(void);
};

struct w3_process_ops {
    int (*observe_leader_fn)(pid_t, int *);
    int (*census_group_fn)(pid_t, pid_t, uint32_t *, int *);
    int (*signal_group_fn)(pid_t, int);
    int (*signal_pid_fn)(pid_t, int);
    int (*reap_leader_fn)(pid_t, int *);
};

typedef int (*w3_activate_socket_fn)(const char *, int **, size_t *);

static char *const w3_child_argv[] = {
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
    W3_RUNTIME_LOADER_FLAGS_JSON,
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

static char *const w3_child_environment[] = {
    "HOME=/var/empty",
    "LANG=C",
    "LC_ALL=C",
    "PATH=/usr/bin:/bin",
    "TMPDIR=.",
    "TZ=UTC",
    NULL,
};

static const struct w3_credential_ops w3_system_credential_ops = {
    .setgroups_fn = setgroups,
    .setgid_fn = setgid,
    .setuid_fn = setuid,
    .getgroups_fn = getgroups,
    .getgid_fn = getgid,
    .getegid_fn = getegid,
    .getuid_fn = getuid,
    .geteuid_fn = geteuid,
};

static uint64_t w3_monotonic_milliseconds(void)
{
    struct timespec now;

    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) {
        return 0U;
    }
    return (uint64_t)now.tv_sec * 1000U + (uint64_t)now.tv_nsec / 1000000U;
}

static int w3_deadline_remaining(uint64_t deadline)
{
    uint64_t now = w3_monotonic_milliseconds();
    uint64_t remaining;

    if (now == 0U || now >= deadline) {
        return 0;
    }
    remaining = deadline - now;
    return remaining > (uint64_t)INT32_MAX ? INT32_MAX : (int)remaining;
}

static int w3_wait_descriptor(int descriptor, short events, uint64_t deadline)
{
    struct pollfd poll_descriptor;

    memset(&poll_descriptor, 0, sizeof(poll_descriptor));
    poll_descriptor.fd = descriptor;
    poll_descriptor.events = events;
    for (;;) {
        int remaining = w3_deadline_remaining(deadline);
        int result;

        if (remaining == 0) {
            errno = ETIMEDOUT;
            return -1;
        }
        result = poll(&poll_descriptor, 1U, remaining);
        if (result > 0) {
            if ((poll_descriptor.revents & (events | POLLHUP)) != 0) {
                return 0;
            }
            errno = EIO;
            return -1;
        }
        if (result == 0) {
            errno = ETIMEDOUT;
            return -1;
        }
        if (errno != EINTR) {
            return -1;
        }
    }
}

static void w3_close_received_rights(struct msghdr *message)
{
    struct cmsghdr *control;

    for (control = CMSG_FIRSTHDR(message); control != NULL;
         control = CMSG_NXTHDR(message, control)) {
        if (control->cmsg_level == SOL_SOCKET &&
            control->cmsg_type == W3_ANCILLARY_RIGHTS_TYPE &&
            control->cmsg_len >= CMSG_LEN(0U)) {
            size_t payload_bytes = control->cmsg_len - CMSG_LEN(0U);
            size_t count = payload_bytes / sizeof(int);
            int *descriptors = (int *)(void *)CMSG_DATA(control);
            size_t index;

            for (index = 0U; index < count; ++index) {
                if (descriptors[index] >= 0) {
                    (void)close(descriptors[index]);
                }
            }
        }
    }
}

static ssize_t w3_recv_without_ancillary(
    int descriptor,
    void *buffer,
    size_t length,
    uint64_t deadline
)
{
    union {
        struct cmsghdr alignment;
        uint8_t bytes[CMSG_SPACE(sizeof(int) * W3_MAX_ANCILLARY_FDS)];
    } control_buffer;
    struct iovec vector;
    struct msghdr message;
    ssize_t count;

    if (w3_wait_descriptor(descriptor, POLLIN, deadline) != 0) {
        return -1;
    }
    memset(&control_buffer, 0, sizeof(control_buffer));
    memset(&message, 0, sizeof(message));
    vector.iov_base = buffer;
    vector.iov_len = length;
    message.msg_iov = &vector;
    message.msg_iovlen = 1U;
    message.msg_control = control_buffer.bytes;
    message.msg_controllen = sizeof(control_buffer.bytes);
    do {
        count = recvmsg (descriptor, &message, 0);
    } while (count < 0 && errno == EINTR);
    if (count < 0) {
        return -1;
    }
    if ((message.msg_flags & MSG_CTRUNC) != 0 || message.msg_controllen != 0U) {
        w3_close_received_rights(&message);
        errno = EPROTO;
        return -1;
    }
    return count;
}

static int w3_recv_exact(
    int descriptor,
    void *buffer,
    size_t length,
    uint64_t deadline
)
{
    uint8_t *cursor = buffer;
    size_t consumed = 0U;

    while (consumed < length) {
        ssize_t count = w3_recv_without_ancillary(
            descriptor,
            cursor + consumed,
            length - consumed,
            deadline
        );
        if (count == 0) {
            errno = ECONNRESET;
            return -1;
        }
        if (count < 0) {
            return -1;
        }
        consumed += (size_t)count;
    }
    return 0;
}

static int w3_require_write_eof(int descriptor, uint64_t deadline)
{
    uint8_t trailing = 0U;
    ssize_t count = w3_recv_without_ancillary(descriptor, &trailing, 1U, deadline);

    if (count == 0) {
        return 0;
    }
    errno = EPROTO;
    return -1;
}

static int w3_send_exact(
    int descriptor,
    const void *buffer,
    size_t length,
    uint64_t deadline
)
{
    const uint8_t *cursor = buffer;
    size_t consumed = 0U;

    while (consumed < length) {
        ssize_t count;

        if (w3_wait_descriptor(descriptor, POLLOUT, deadline) != 0) {
            return -1;
        }
        do {
            count = send(descriptor, cursor + consumed, length - consumed, 0);
        } while (count < 0 && errno == EINTR);
        if (count <= 0) {
            if (count == 0) {
                errno = EPIPE;
            }
            return -1;
        }
        consumed += (size_t)count;
    }
    return 0;
}

static int w3_validate_request_header(
    const struct w3_launcher_request_header *header,
    uint32_t *payload_length
)
{
    uint32_t version;
    uint32_t length;

    if (memcmp(header->magic, W3_LAUNCHER_MAGIC, W3_LAUNCHER_MAGIC_BYTES) != 0) {
        errno = EPROTO;
        return -1;
    }
    version = ntohl(header->version_be);
    length = ntohl(header->payload_length_be);
    if (version != W3_LAUNCHER_PROTOCOL_VERSION || length == 0U ||
        length > W3_LAUNCHER_MAX_PAYLOAD_BYTES) {
        errno = EPROTO;
        return -1;
    }
    *payload_length = length;
    return 0;
}

static int w3_receive_request_frame(int descriptor, struct w3_request_frame *frame)
{
    uint64_t deadline = w3_monotonic_milliseconds() + W3_FRAME_TIMEOUT_MS;

    memset(frame, 0, sizeof(*frame));
    if (w3_recv_exact(descriptor, &frame->header, sizeof(frame->header), deadline) != 0 ||
        w3_validate_request_header(&frame->header, &frame->payload_length) != 0) {
        return -1;
    }
    frame->payload = calloc(frame->payload_length, 1U);
    if (frame->payload == NULL) {
        return -1;
    }
    if (w3_recv_exact(descriptor, frame->payload, frame->payload_length, deadline) != 0 ||
        w3_require_write_eof(descriptor, deadline) != 0) {
        free(frame->payload);
        frame->payload = NULL;
        frame->payload_length = 0U;
        return -1;
    }
    return 0;
}

static void w3_free_request_frame(struct w3_request_frame *frame)
{
    if (frame->payload != NULL) {
        memset(frame->payload, 0, frame->payload_length);
        free(frame->payload);
    }
    memset(frame, 0, sizeof(*frame));
}

static int w3_authorize_broker_peer_as(int descriptor, uid_t expected_uid, gid_t expected_gid)
{
    uid_t peer_uid = (uid_t)-1;
    gid_t peer_gid = (gid_t)-1;

    if (expected_uid == (uid_t)-1 || expected_gid == (gid_t)-1 ||
        getpeereid(descriptor, &peer_uid, &peer_gid) != 0) {
        return -1;
    }
    if (peer_uid != expected_uid || peer_gid != expected_gid) {
        errno = EACCES;
        return -1;
    }
    return 0;
}

static int w3_authorize_broker_peer(
    int descriptor,
    uid_t *peer_uid_out,
    gid_t *peer_gid_out
)
{
    uid_t peer_uid = (uid_t)-1;
    gid_t peer_gid = (gid_t)-1;

    if (peer_uid_out == NULL || peer_gid_out == NULL ||
        W3_BROKER_UID == (uid_t)-1 || W3_BROKER_GID == (gid_t)-1 ||
        getpeereid(descriptor, &peer_uid, &peer_gid) != 0) {
        return -1;
    }
    if (peer_uid != W3_BROKER_UID || peer_gid != W3_BROKER_GID) {
        errno = EACCES;
        return -1;
    }
    *peer_uid_out = peer_uid;
    *peer_gid_out = peer_gid;
    return 0;
}

static int w3_set_close_on_exec(int descriptor, int enabled)
{
    int flags = fcntl(descriptor, F_GETFD);

    if (flags < 0) {
        return -1;
    }
    flags = enabled ? flags | FD_CLOEXEC : flags & ~FD_CLOEXEC;
    return fcntl(descriptor, F_SETFD, flags);
}

static int w3_set_nonblocking(int descriptor)
{
    int flags = fcntl(descriptor, F_GETFL);

    if (flags < 0) {
        return -1;
    }
    return fcntl(descriptor, F_SETFL, flags | O_NONBLOCK);
}

static int w3_prepare_supervisor_signal_policy(void)
{
    struct sigaction ignore_pipe;
    struct sigaction default_child;

    memset(&ignore_pipe, 0, sizeof(ignore_pipe));
    memset(&default_child, 0, sizeof(default_child));
    ignore_pipe.sa_handler = SIG_IGN;
    default_child.sa_handler = SIG_DFL;
    return sigemptyset(&ignore_pipe.sa_mask) == 0 &&
                   sigemptyset(&default_child.sa_mask) == 0 &&
                   sigaction(SIGPIPE, &ignore_pipe, NULL) == 0 &&
                   sigaction(SIGCHLD, &default_child, NULL) == 0
               ? 0
               : -1;
}

static int w3_close_child_fds(int allowed_descriptor)
{
    long maximum = sysconf(_SC_OPEN_MAX);
    int descriptor;

    if (maximum < 0 || maximum > 1048576L) {
        maximum = 65536L;
    }
    for (descriptor = STDERR_FILENO + 1; descriptor < maximum; ++descriptor) {
        if (descriptor == allowed_descriptor) {
            continue;
        }
        if (close(descriptor) != 0 && errno != EBADF) {
            return -1;
        }
    }
    return 0;
}

static int w3_drop_with_ops(const struct w3_credential_ops *ops)
{
    int supplementary_count;

    if (ops == NULL || W3_RUNNER_UID == (uid_t)-1 || W3_RUNNER_GID == (gid_t)-1 ||
        W3_RUNNER_UID == 0 || W3_RUNNER_GID == 0 || W3_RUNNER_UID == W3_BROKER_UID ||
        W3_RUNNER_GID == W3_BROKER_GID) {
        errno = EINVAL;
        return -1;
    }
    if (ops->setgroups_fn(0, NULL) != 0 || ops->setgid_fn(W3_RUNNER_GID) != 0 ||
        ops->setuid_fn(W3_RUNNER_UID) != 0) {
        return -1;
    }
    supplementary_count = ops->getgroups_fn(0, NULL);
    if (supplementary_count != 0 || ops->getgid_fn() != W3_RUNNER_GID ||
        ops->getegid_fn() != W3_RUNNER_GID || ops->getuid_fn() != W3_RUNNER_UID ||
        ops->geteuid_fn() != W3_RUNNER_UID) {
        errno = EPERM;
        return -1;
    }
    errno = 0;
    if (ops->setuid_fn(0) == 0 || errno != EPERM) {
        errno = EPERM;
        return -1;
    }
    errno = 0;
    if (ops->setgid_fn(0) == 0 || errno != EPERM) {
        errno = EPERM;
        return -1;
    }
    if (ops->getgid_fn() != W3_RUNNER_GID || ops->getegid_fn() != W3_RUNNER_GID ||
        ops->getuid_fn() != W3_RUNNER_UID || ops->geteuid_fn() != W3_RUNNER_UID) {
        errno = EPERM;
        return -1;
    }
    return 0;
}

static int w3_drop_irreversibly_to_runner(void)
{
    int supplementary_count;

    if (W3_RUNNER_UID == (uid_t)-1 || W3_RUNNER_GID == (gid_t)-1 ||
        W3_RUNNER_UID == 0 || W3_RUNNER_GID == 0 || W3_RUNNER_UID == W3_BROKER_UID ||
        W3_RUNNER_GID == W3_BROKER_GID) {
        errno = EINVAL;
        return -1;
    }
    if (setgroups(0, NULL) != 0 || setgid(W3_RUNNER_GID) != 0 ||
        setuid(W3_RUNNER_UID) != 0) {
        return -1;
    }
    supplementary_count = getgroups(0, NULL);
    if (supplementary_count != 0 || getgid() != W3_RUNNER_GID ||
        getegid() != W3_RUNNER_GID || getuid() != W3_RUNNER_UID ||
        geteuid() != W3_RUNNER_UID) {
        errno = EPERM;
        return -1;
    }
    errno = 0;
    if (setuid(0) == 0 || errno != EPERM) {
        errno = EPERM;
        return -1;
    }
    errno = 0;
    if (setgid(0) == 0 || errno != EPERM) {
        errno = EPERM;
        return -1;
    }
    if (getgid() != W3_RUNNER_GID || getegid() != W3_RUNNER_GID ||
        getuid() != W3_RUNNER_UID || geteuid() != W3_RUNNER_UID) {
        errno = EPERM;
        return -1;
    }
    return 0;
}

static int w3_is_lower_hex(const char *value, size_t length)
{
    size_t index;

    if (value == NULL || strlen(value) != length) {
        return 0;
    }
    for (index = 0U; index < length; ++index) {
        if (!((value[index] >= '0' && value[index] <= '9') ||
              (value[index] >= 'a' && value[index] <= 'f'))) {
            return 0;
        }
    }
    return 1;
}

static int w3_configuration_is_frozen(void)
{
    static const char *const installed_paths[] = {
        W3_LAUNCHER_SOCKET_PATH,
        W3_RELEASE_ROOT,
        W3_SANDBOX_EXEC_PATH,
        W3_SEATBELT_POLICY_PATH,
        W3_NODE_PATH,
        W3_METIS_ROOT,
        W3_LOADER_PATH,
        W3_RUNNER_PATH,
        W3_RUN_PARENT,
        W3_RUN_ROOT,
    };
    static const char *const sha256_pins[] = {
        W3_TOOLING_PACKAGE_SHA256,
        W3_TOOLING_LOCK_SHA256,
        W3_NODE_MODULES_SHA256,
        W3_RUNNER_SHA256,
        W3_LOADER_SHA256,
        W3_NODE_BINARY_SHA256,
        W3_ORACLE_POLICY_SHA256,
        W3_EXECUTION_POLICY_SHA256,
        W3_SEATBELT_POLICY_SHA256,
    };
    size_t index;

    if (W3_BROKER_UID == (uid_t)-1 || W3_BROKER_GID == (gid_t)-1 ||
        W3_RUNNER_UID == (uid_t)-1 || W3_RUNNER_GID == (gid_t)-1 ||
        W3_BROKER_UID == 0 || W3_BROKER_GID == 0 || W3_RUNNER_UID == 0 ||
        W3_RUNNER_GID == 0 || W3_BROKER_UID == W3_RUNNER_UID ||
        W3_BROKER_GID == W3_RUNNER_GID) {
        return 0;
    }
#ifndef W3_LOCAL_SIMULATION
    if (W3_RUN_PARENT_UID != 0 || W3_RUN_PARENT_GID != 0 ||
        W3_RUN_LEAF_UID != W3_RUNNER_UID || W3_RUN_LEAF_GID != W3_RUNNER_GID ||
        W3_SEATBELT_POLICY_UID != 0 || W3_SEATBELT_POLICY_GID != 0 ||
        W3_SEATBELT_POLICY_MODE != (mode_t)0444) {
        return 0;
    }
#endif
    if (strcmp(W3_RUN_LEAF_NAME, "active") != 0 ||
        !w3_is_lower_hex(W3_METIS_REVISION, 40U) ||
        !w3_is_lower_hex(W3_METIS_TREE, 40U) ||
        strcmp(W3_RUNTIME_LOADER_FLAGS_JSON,
               "[\"--disable-warning=ExperimentalWarning\",\"--experimental-loader\"]") != 0) {
        return 0;
    }
    for (index = 0U; index < sizeof(installed_paths) / sizeof(installed_paths[0]); ++index) {
        if (installed_paths[index][0] != '/' || strstr(installed_paths[index], "/UNSET") != NULL) {
            return 0;
        }
    }
    for (index = 0U; index < sizeof(sha256_pins) / sizeof(sha256_pins[0]); ++index) {
        if (!w3_is_lower_hex(sha256_pins[index], 64U)) {
            return 0;
        }
    }
    return 1;
}

static int w3_validate_listener_descriptor(int descriptor)
{
    int socket_type = 0;
    socklen_t option_length = sizeof(socket_type);
    struct sockaddr_un address;
    socklen_t address_length = sizeof(address);
    const size_t expected_path_length = strlen(W3_LAUNCHER_SOCKET_PATH);
    const size_t expected_address_length =
        offsetof(struct sockaddr_un, sun_path) + expected_path_length + 1U;

    memset(&address, 0xa5, sizeof(address));
    if (expected_path_length == 0U || expected_path_length >= sizeof(address.sun_path) ||
        expected_address_length > (size_t)((socklen_t)-1) || descriptor < 0 ||
        getsockopt(descriptor, SOL_SOCKET, SO_TYPE, &socket_type, &option_length) != 0 ||
        option_length != sizeof(socket_type) || socket_type != SOCK_STREAM) {
        errno = EPROTOTYPE;
        return -1;
    }
    if (getsockname(descriptor, (struct sockaddr *)&address, &address_length) != 0 ||
        address_length != (socklen_t)expected_address_length ||
        address.sun_family != AF_UNIX ||
        address.sun_path[expected_path_length] != '\0' ||
        memcmp(address.sun_path, W3_LAUNCHER_SOCKET_PATH, expected_path_length) != 0) {
        errno = EPROTOTYPE;
        return -1;
    }
#if defined(__APPLE__)
    if (address.sun_len != (uint8_t)expected_address_length) {
        errno = EPROTOTYPE;
        return -1;
    }
#endif
    return 0;
}

static int w3_activate_listener_with(w3_activate_socket_fn activate_fn, int *listener_out)
{
    int *descriptors = NULL;
    size_t count = 0U;
    int activation_error;
    size_t index;

    if (activate_fn == NULL || listener_out == NULL) {
        errno = EINVAL;
        return -1;
    }
    activation_error = activate_fn("LauncherListener", &descriptors, &count);
    if (activation_error != 0) {
        errno = activation_error;
        return -1;
    }
    if (descriptors == NULL || count != 1U ||
        w3_validate_listener_descriptor(descriptors[0]) != 0) {
        int saved_errno = errno == 0 ? EPROTO : errno;

        if (descriptors != NULL) {
            for (index = 0U; index < count; ++index) {
                if (descriptors[index] >= 0) {
                    (void)close(descriptors[index]);
                }
            }
        }
        free(descriptors);
        errno = saved_errno;
        return -1;
    }
    *listener_out = descriptors[0];
    free(descriptors);
    if (w3_set_close_on_exec(*listener_out, 1) != 0) {
        int saved_errno = errno;

        (void)close(*listener_out);
        *listener_out = -1;
        errno = saved_errno;
        return -1;
    }
    return 0;
}

static int w3_make_pipe(int descriptors[2])
{
    if (pipe(descriptors) != 0) {
        return -1;
    }
    if (w3_set_close_on_exec(descriptors[0], 1) != 0 ||
        w3_set_close_on_exec(descriptors[1], 1) != 0) {
        int saved_errno = errno;

        (void)close(descriptors[0]);
        (void)close(descriptors[1]);
        errno = saved_errno;
        return -1;
    }
    return 0;
}

static int w3_same_file_identity(const struct stat *left, const struct stat *right)
{
    return left->st_dev == right->st_dev && left->st_ino == right->st_ino &&
           left->st_uid == right->st_uid && left->st_gid == right->st_gid &&
           left->st_mode == right->st_mode && left->st_nlink == right->st_nlink;
}

static int w3_policy_contains_bytes(
    const uint8_t *bytes,
    size_t length,
    const char *wanted
)
{
    size_t wanted_length = strlen(wanted);
    size_t offset;

    if (wanted_length == 0U || wanted_length > length) {
        return 0;
    }
    for (offset = 0U; offset <= length - wanted_length; ++offset) {
        if (memcmp(bytes + offset, wanted, wanted_length) == 0) {
            return 1;
        }
    }
    return 0;
}

static int w3_policy_is_concrete_and_bound(const uint8_t *bytes, size_t length)
{
    size_t index;

    for (index = 0U; index < length; ++index) {
        if (bytes[index] == 0U) {
            return 0;
        }
    }
    return !w3_policy_contains_bytes(bytes, length, "(param") &&
           w3_policy_contains_bytes(bytes, length, "(version 1)") &&
           w3_policy_contains_bytes(bytes, length, "(deny default)") &&
           w3_policy_contains_bytes(bytes, length, "(deny network*)") &&
           w3_policy_contains_bytes(bytes, length, "(deny process-fork)") &&
           w3_policy_contains_bytes(bytes, length, "(allow process-exec") &&
           w3_policy_contains_bytes(bytes, length, "(allow file-write*") &&
           w3_policy_contains_bytes(bytes, length, W3_NODE_PATH) &&
           w3_policy_contains_bytes(bytes, length, W3_METIS_ROOT) &&
           w3_policy_contains_bytes(bytes, length, W3_RUN_ROOT);
}

static int w3_seatbelt_policy_metadata_is_valid(const struct stat *metadata)
{
    return S_ISREG(metadata->st_mode) && metadata->st_uid == W3_SEATBELT_POLICY_UID &&
           metadata->st_gid == W3_SEATBELT_POLICY_GID && metadata->st_nlink == 1 &&
           (metadata->st_mode & 07777) == W3_SEATBELT_POLICY_MODE &&
           metadata->st_size > 0 &&
           (uint64_t)metadata->st_size <= W3_MAX_SEATBELT_POLICY_BYTES;
}

static int w3_validate_seatbelt_policy(void)
{
    static const char hex_digits[] = "0123456789abcdef";
    struct stat by_descriptor;
    struct stat by_name;
    struct stat after_read;
    uint8_t digest[W3_SHA256_BYTES];
    char digest_hex[W3_SHA256_BYTES * 2U + 1U];
    uint8_t *bytes = NULL;
    size_t length = 0U;
    size_t offset = 0U;
    int descriptor = -1;
    int outcome = -1;
    size_t index;

    descriptor = open(W3_SEATBELT_POLICY_PATH, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (descriptor < 0 || fstat(descriptor, &by_descriptor) != 0 ||
        lstat(W3_SEATBELT_POLICY_PATH, &by_name) != 0 ||
        !w3_seatbelt_policy_metadata_is_valid(&by_descriptor) ||
        !w3_seatbelt_policy_metadata_is_valid(&by_name) ||
        !w3_same_file_identity(&by_descriptor, &by_name)) {
        errno = EPERM;
        goto cleanup;
    }
    length = (size_t)by_descriptor.st_size;
    bytes = malloc(length);
    if (bytes == NULL) {
        goto cleanup;
    }
    while (offset < length) {
        ssize_t count = read(descriptor, bytes + offset, length - offset);

        if (count > 0) {
            offset += (size_t)count;
        } else if (count < 0 && errno == EINTR) {
            continue;
        } else {
            errno = ESTALE;
            goto cleanup;
        }
    }
    {
        uint8_t trailing;
        ssize_t count;

        do {
            count = read(descriptor, &trailing, 1U);
        } while (count < 0 && errno == EINTR);
        if (count != 0 || fstat(descriptor, &after_read) != 0 ||
            lstat(W3_SEATBELT_POLICY_PATH, &by_name) != 0 ||
            !w3_same_file_identity(&by_descriptor, &after_read) ||
            !w3_same_file_identity(&by_descriptor, &by_name)) {
            errno = ESTALE;
            goto cleanup;
        }
        if (!w3_policy_is_concrete_and_bound(bytes, length)) {
            errno = EPROTOTYPE;
            goto cleanup;
        }
    }
    (void)CC_SHA256(bytes, (CC_LONG)length, digest);
    for (index = 0U; index < W3_SHA256_BYTES; ++index) {
        digest_hex[index * 2U] = hex_digits[digest[index] >> 4U];
        digest_hex[index * 2U + 1U] = hex_digits[digest[index] & 0x0fU];
    }
    digest_hex[sizeof(digest_hex) - 1U] = '\0';
    if (strcmp(digest_hex, W3_SEATBELT_POLICY_SHA256) != 0) {
        errno = EAUTH;
        goto cleanup;
    }
    outcome = 0;

cleanup:
    {
        int saved_errno = errno;

        free(bytes);
        if (descriptor >= 0) {
            (void)close(descriptor);
        }
        errno = saved_errno;
        return outcome;
    }
}

static int w3_run_parent_metadata_is_valid(const struct stat *metadata)
{
    return S_ISDIR(metadata->st_mode) && metadata->st_uid == W3_RUN_PARENT_UID &&
           metadata->st_gid == W3_RUN_PARENT_GID && metadata->st_nlink > 0 &&
           (metadata->st_mode & 0777) == 0711;
}

static int w3_run_leaf_metadata_is_valid(const struct stat *metadata)
{
    return S_ISDIR(metadata->st_mode) && metadata->st_uid == W3_RUN_LEAF_UID &&
           metadata->st_gid == W3_RUN_LEAF_GID && metadata->st_nlink > 0 &&
           (metadata->st_mode & 0777) == 0700;
}

static void w3_close_run_root_anchor(struct w3_run_root_anchor *anchor)
{
    if (anchor->leaf_fd >= 0) {
        (void)close(anchor->leaf_fd);
    }
    if (anchor->parent_fd >= 0) {
        (void)close(anchor->parent_fd);
    }
    anchor->leaf_fd = -1;
    anchor->parent_fd = -1;
}

static int w3_reverify_run_root_anchor(const struct w3_run_root_anchor *anchor)
{
    struct stat parent_by_fd;
    struct stat parent_by_name;
    struct stat leaf_by_fd;
    struct stat leaf_by_name;

    if (anchor == NULL || anchor->parent_fd < 0 || anchor->leaf_fd < 0 ||
        fstat(anchor->parent_fd, &parent_by_fd) != 0 ||
        lstat(W3_RUN_PARENT, &parent_by_name) != 0 ||
        fstat(anchor->leaf_fd, &leaf_by_fd) != 0 ||
        fstatat(
            anchor->parent_fd,
            W3_RUN_LEAF_NAME,
            &leaf_by_name,
            AT_SYMLINK_NOFOLLOW
        ) != 0 ||
        !w3_run_parent_metadata_is_valid(&parent_by_fd) ||
        !w3_run_leaf_metadata_is_valid(&leaf_by_fd) ||
        !w3_same_file_identity(&anchor->parent_identity, &parent_by_fd) ||
        !w3_same_file_identity(&anchor->parent_identity, &parent_by_name) ||
        !w3_same_file_identity(&anchor->leaf_identity, &leaf_by_fd) ||
        !w3_same_file_identity(&anchor->leaf_identity, &leaf_by_name)) {
        errno = ESTALE;
        return -1;
    }
    return 0;
}

static int w3_open_run_root_anchor(struct w3_run_root_anchor *anchor)
{
    memset(anchor, 0, sizeof(*anchor));
    anchor->parent_fd = -1;
    anchor->leaf_fd = -1;
    anchor->parent_fd = open(
        W3_RUN_PARENT,
        O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC
    );
    if (anchor->parent_fd < 0 || fstat(anchor->parent_fd, &anchor->parent_identity) != 0 ||
        !w3_run_parent_metadata_is_valid(&anchor->parent_identity)) {
        goto failure;
    }
    anchor->leaf_fd = openat(
        anchor->parent_fd,
        W3_RUN_LEAF_NAME,
        O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC
    );
    if (anchor->leaf_fd < 0 || fstat(anchor->leaf_fd, &anchor->leaf_identity) != 0 ||
        !w3_run_leaf_metadata_is_valid(&anchor->leaf_identity) ||
        w3_reverify_run_root_anchor(anchor) != 0) {
        goto failure;
    }
    return 0;

failure:
    {
        int saved_errno = errno == 0 ? EPERM : errno;

        w3_close_run_root_anchor(anchor);
        errno = saved_errno;
        return -1;
    }
}

static uint32_t w3_count_temp_entries_at(int leaf_fd)
{
    int duplicate = fcntl(leaf_fd, F_DUPFD_CLOEXEC, STDERR_FILENO + 1);
    DIR *directory;
    struct dirent *entry;
    uint32_t count = 0U;

    if (duplicate < 0) {
        return UINT32_MAX;
    }
    directory = fdopendir(duplicate);
    if (directory == NULL) {
        (void)close(duplicate);
        return UINT32_MAX;
    }
    errno = 0;
    while ((entry = readdir(directory)) != NULL) {
        if (strcmp(entry->d_name, ".") == 0 || strcmp(entry->d_name, "..") == 0) {
            continue;
        }
        if (count == UINT32_MAX - 1U) {
            count = UINT32_MAX;
            break;
        }
        ++count;
    }
    if (entry == NULL && errno != 0) {
        count = UINT32_MAX;
    }
    if (closedir(directory) != 0) {
        count = UINT32_MAX;
    }
    return count;
}

static uint32_t w3_wait_kind(int wait_status)
{
    if (WIFEXITED(wait_status)) {
        return W3_WAIT_EXITED;
    }
    if (WIFSIGNALED(wait_status)) {
        return W3_WAIT_SIGNALED;
    }
    return W3_WAIT_UNAVAILABLE;
}

static uint32_t w3_wait_value(int wait_status)
{
    if (WIFEXITED(wait_status)) {
        return (uint32_t)WEXITSTATUS(wait_status);
    }
    if (WIFSIGNALED(wait_status)) {
        return (uint32_t)WTERMSIG(wait_status);
    }
    return 0U;
}

static int w3_observe_leader_without_reaping(pid_t leader, int *terminal_out)
{
    siginfo_t information;
    int outcome;

    memset(&information, 0, sizeof(information));
    do {
        outcome = waitid(
            P_PID,
            (id_t)leader,
            &information,
            WEXITED | WNOHANG | WNOWAIT
        );
    } while (outcome != 0 && errno == EINTR);
    if (outcome != 0) {
        return -1;
    }
    *terminal_out = information.si_pid == leader;
    return 0;
}

static int w3_pid_count_from_census_bytes(
    int returned_bytes,
    size_t buffer_bytes,
    size_t *pid_count_out
)
{
    if (returned_bytes <= 0 || (size_t)returned_bytes >= buffer_bytes ||
        (size_t)returned_bytes % sizeof(pid_t) != 0U) {
        errno = returned_bytes < 0 ? errno : EOVERFLOW;
        return -1;
    }
    *pid_count_out = (size_t)returned_bytes / sizeof(pid_t);
    return 0;
}

static int w3_census_process_group(
    pid_t process_group,
    pid_t leader,
    uint32_t *other_members_out,
    int *leader_present_out
)
{
    pid_t identifiers[W3_MAX_PROCESS_GROUP_PIDS];
    int returned_bytes;
    size_t pid_count;
    size_t index;
    uint32_t other_members = 0U;
    int leader_present = 0;

    memset(identifiers, 0, sizeof(identifiers));
    returned_bytes = proc_listpids(
        PROC_PGRP_ONLY,
        (uint32_t)process_group,
        identifiers,
        (int)sizeof(identifiers)
    );
    if (w3_pid_count_from_census_bytes(
            returned_bytes,
            sizeof(identifiers),
            &pid_count
        ) != 0) {
        return -1;
    }
    for (index = 0U; index < pid_count; ++index) {
        if (identifiers[index] <= 0) {
            errno = EPROTO;
            return -1;
        }
        if (identifiers[index] == leader) {
            if (leader_present) {
                errno = EPROTO;
                return -1;
            }
            leader_present = 1;
        } else {
            ++other_members;
        }
    }
    *other_members_out = other_members;
    *leader_present_out = leader_present;
    return 0;
}

static int w3_signal_process_group(pid_t process_group, int signal_number)
{
    return kill(-process_group, signal_number);
}

static int w3_signal_process(pid_t process, int signal_number)
{
    return kill(process, signal_number);
}

static int w3_reap_leader(pid_t leader, int *wait_status)
{
    pid_t waited;

    do {
        waited = waitpid(leader, wait_status, 0);
    } while (waited < 0 && errno == EINTR);
    return waited == leader ? 0 : -1;
}

static const struct w3_process_ops w3_system_process_ops = {
    .observe_leader_fn = w3_observe_leader_without_reaping,
    .census_group_fn = w3_census_process_group,
    .signal_group_fn = w3_signal_process_group,
    .signal_pid_fn = w3_signal_process,
    .reap_leader_fn = w3_reap_leader,
};

static int w3_group_is_terminal_and_singleton(
    pid_t leader,
    const struct w3_process_ops *ops,
    int *leader_terminal_out
)
{
    uint32_t other_members = UINT32_MAX;
    int leader_present = 0;
    int leader_terminal = 0;

    if (ops->observe_leader_fn(leader, &leader_terminal) != 0 ||
        ops->census_group_fn(
            leader,
            leader,
            &other_members,
            &leader_present
        ) != 0) {
        return -1;
    }
    *leader_terminal_out = leader_terminal;
    return leader_terminal && leader_present && other_members == 0U;
}

static uint32_t w3_terminate_and_reap_group_with(
    pid_t child,
    int *wait_status,
    int *reaped,
    const struct w3_process_ops *ops
)
{
    static const int signals[] = {SIGTERM, SIGKILL};
    int leader_terminal = 0;
    int clean = 0;
    size_t phase;

    if (child <= 0 || wait_status == NULL || reaped == NULL || ops == NULL ||
        ops->observe_leader_fn == NULL || ops->census_group_fn == NULL ||
        ops->signal_group_fn == NULL || ops->signal_pid_fn == NULL ||
        ops->reap_leader_fn == NULL || *reaped) {
        return 1U;
    }
    clean = w3_group_is_terminal_and_singleton(child, ops, &leader_terminal) == 1;
    for (phase = 0U; !clean && phase < sizeof(signals) / sizeof(signals[0]); ++phase) {
        uint64_t deadline = w3_monotonic_milliseconds() + W3_TERM_GRACE_MS;

        (void)ops->signal_group_fn(child, signals[phase]);
        do {
            int state = w3_group_is_terminal_and_singleton(
                child,
                ops,
                &leader_terminal
            );

            if (state == 1) {
                clean = 1;
                break;
            }
            if (w3_deadline_remaining(deadline) == 0) {
                break;
            }
            (void)poll(NULL, 0U, 5);
        } while (1);
    }

    /* Reaping is deliberately the final PID/PGID operation. */
    if (clean && leader_terminal && ops->reap_leader_fn(child, wait_status) == 0) {
        *reaped = 1;
    } else {
        clean = 0;
    }
    return clean && *reaped ? 0U : 1U;
}

static uint32_t w3_terminate_and_reap_pid_with(
    pid_t child,
    int *wait_status,
    int *reaped,
    const struct w3_process_ops *ops
)
{
    static const int signals[] = {SIGTERM, SIGKILL};
    int leader_terminal = 0;
    size_t phase;

    if (child <= 0 || wait_status == NULL || reaped == NULL || ops == NULL ||
        ops->observe_leader_fn == NULL || ops->signal_pid_fn == NULL ||
        ops->reap_leader_fn == NULL || *reaped) {
        return 1U;
    }
    if (ops->observe_leader_fn(child, &leader_terminal) != 0) {
        leader_terminal = 0;
    }
    for (phase = 0U;
         !leader_terminal && phase < sizeof(signals) / sizeof(signals[0]);
         ++phase) {
        uint64_t deadline = w3_monotonic_milliseconds() + W3_TERM_GRACE_MS;

        (void)ops->signal_pid_fn(child, signals[phase]);
        do {
            if (ops->observe_leader_fn(child, &leader_terminal) == 0 &&
                leader_terminal) {
                break;
            }
            if (w3_deadline_remaining(deadline) == 0) {
                break;
            }
            (void)poll(NULL, 0U, 5);
        } while (1);
    }
    /* Reaping is deliberately the final numeric PID operation. */
    if (leader_terminal && ops->reap_leader_fn(child, wait_status) == 0) {
        *reaped = 1;
        return 0U;
    }
    return 1U;
}

static uint32_t w3_terminate_and_reap_pid(pid_t child, int *wait_status, int *reaped)
{
    return w3_terminate_and_reap_pid_with(
        child,
        wait_status,
        reaped,
        &w3_system_process_ops
    );
}

static uint32_t w3_terminate_and_reap_group(pid_t child, int *wait_status, int *reaped)
{
    return w3_terminate_and_reap_group_with(
        child,
        wait_status,
        reaped,
        &w3_system_process_ops
    );
}

static uint32_t w3_count_retained_pipe_fds(const int *descriptors, size_t count)
{
    uint32_t retained = 0U;
    size_t index;

    for (index = 0U; index < count; ++index) {
        if (descriptors[index] >= 0 && fcntl(descriptors[index], F_GETFD) >= 0) {
            ++retained;
        }
    }
    return retained;
}

static void w3_close_retained_pipe_fds(const int *descriptors, size_t count)
{
    size_t index;

    for (index = 0U; index < count; ++index) {
        if (descriptors[index] >= 0 && fcntl(descriptors[index], F_GETFD) >= 0) {
            (void)close(descriptors[index]);
        }
    }
}

static int w3_append_output(
    int descriptor,
    uint8_t *buffer,
    uint32_t *length,
    uint32_t maximum,
    int *open_flag
)
{
    uint8_t chunk[W3_IO_CHUNK_BYTES];

    for (;;) {
        ssize_t count = read(descriptor, chunk, sizeof(chunk));
        if (count > 0) {
            if ((uint64_t)*length + (uint64_t)count > maximum) {
                errno = EFBIG;
                return -1;
            }
            memcpy(buffer + *length, chunk, (size_t)count);
            *length += (uint32_t)count;
            continue;
        }
        if (count == 0) {
            (void)close(descriptor);
            *open_flag = 0;
            return 0;
        }
        if (errno == EINTR) {
            continue;
        }
        if (errno == EAGAIN || errno == EWOULDBLOCK) {
            return 0;
        }
        return -1;
    }
}

static void w3_fill_cleanup_record(struct w3_execution_result *result)
{
    struct w3_launcher_cleanup_record *record = &result->cleanup;

    memset(record, 0, sizeof(*record));
    memcpy(record->magic, W3_LAUNCHER_CLEANUP_MAGIC, W3_LAUNCHER_MAGIC_BYTES);
    record->version_be = htonl(W3_LAUNCHER_CLEANUP_VERSION);
    record->flags_be = htonl(result->flags);
    record->process_group_residual_be = htonl(result->process_group_residual);
    record->retained_fds_be = htonl(result->retained_fds);
    record->temp_entries_be = htonl(result->temp_entries);
    record->wait_kind_be = htonl(result->wait_kind);
    record->wait_value_be = htonl(result->wait_value);
    record->stdout_length_be = htonl(result->stdout_length);
    record->stderr_length_be = htonl(result->stderr_length);
    record->broker_peer_uid_be = htonl(result->broker_peer_uid);
    record->broker_peer_gid_be = htonl(result->broker_peer_gid);
    record->launcher_uid_be = htonl(result->launcher_uid);
    record->launcher_gid_be = htonl(result->launcher_gid);
    record->runner_uid_be = htonl(result->runner_uid);
    record->runner_gid_be = htonl(result->runner_gid);
    record->child_boundary_succeeded_be = htonl(result->child_boundary_succeeded);
}

static void w3_free_execution_result(struct w3_execution_result *result)
{
    if (result->stdout_bytes != NULL) {
        memset(result->stdout_bytes, 0, result->stdout_length);
        free(result->stdout_bytes);
    }
    if (result->stderr_bytes != NULL) {
        memset(result->stderr_bytes, 0, result->stderr_length);
        free(result->stderr_bytes);
    }
    memset(result, 0, sizeof(*result));
}

/*
 * Phase-A keeps the accepted inert entrypoint and its exact ENOTSUP contract.
 * Installed operation calls the separately named Phase-B implementation below.
 */
static int w3_launch_registered_node(
    const uint8_t *payload,
    uint32_t payload_length,
    struct w3_launcher_response_header *response
)
{
    (void)payload;
    (void)payload_length;
    (void)response;
    errno = ENOTSUP;
    return -1;
}

#ifdef W3_PRIVILEGED_LAUNCHER_PHASE_B
static int w3_phase_b_launch_registered_node(
    const uint8_t *payload,
    uint32_t payload_length,
    uid_t broker_peer_uid,
    gid_t broker_peer_gid,
    struct w3_execution_result *result
)
{
    static const uint8_t child_boundary_marker = 0xa5U;
    struct w3_run_root_anchor run_anchor = {
        .parent_fd = -1,
        .leaf_fd = -1,
    };
    int input_pipe[2] = {-1, -1};
    int output_pipe[2] = {-1, -1};
    int error_pipe[2] = {-1, -1};
    int status_pipe[2] = {-1, -1};
    int tracked_parent_fds[10] = {-1, -1, -1, -1, -1, -1, -1, -1, -1, -1};
    pid_t child = -1;
    uint32_t input_offset = 0U;
    int input_open = 0;
    int output_open = 0;
    int error_open = 0;
    int status_open = 0;
    int group_established = 0;
    int child_reaped = 0;
    int wait_status = 0;
    int failure = 0;
    int output_capped = 0;
    int timed_out = 0;
    uint64_t deadline;

    memset(result, 0, sizeof(*result));
    result->status = W3_LAUNCHER_STATUS_LAUNCH_FAILED;
    result->temp_entries = UINT32_MAX;
    result->broker_peer_uid = (uint32_t)broker_peer_uid;
    result->broker_peer_gid = (uint32_t)broker_peer_gid;
    result->launcher_uid = (uint32_t)geteuid();
    result->launcher_gid = (uint32_t)getegid();
    result->runner_uid = (uint32_t)W3_RUNNER_UID;
    result->runner_gid = (uint32_t)W3_RUNNER_GID;
    if (w3_prepare_supervisor_signal_policy() != 0 || payload == NULL || payload_length == 0U ||
        payload_length > W3_LAUNCHER_MAX_PAYLOAD_BYTES ||
        broker_peer_uid != W3_BROKER_UID || broker_peer_gid != W3_BROKER_GID ||
        result->launcher_uid != 0U || result->launcher_gid != 0U) {
        errno = EINVAL;
        return -1;
    }
    result->stdout_bytes = calloc(W3_MAX_STDOUT_BYTES + 1U, 1U);
    result->stderr_bytes = calloc(W3_MAX_STDERR_BYTES + 1U, 1U);
    if (result->stdout_bytes == NULL || result->stderr_bytes == NULL ||
        w3_validate_seatbelt_policy() != 0 ||
        w3_open_run_root_anchor(&run_anchor) != 0 ||
        w3_make_pipe(input_pipe) != 0 || w3_make_pipe(output_pipe) != 0 ||
        w3_make_pipe(error_pipe) != 0 || w3_make_pipe(status_pipe) != 0) {
        goto setup_failure;
    }
    tracked_parent_fds[0] = run_anchor.parent_fd;
    tracked_parent_fds[1] = run_anchor.leaf_fd;
    tracked_parent_fds[2] = input_pipe[0];
    tracked_parent_fds[3] = input_pipe[1];
    tracked_parent_fds[4] = output_pipe[0];
    tracked_parent_fds[5] = output_pipe[1];
    tracked_parent_fds[6] = error_pipe[0];
    tracked_parent_fds[7] = error_pipe[1];
    tracked_parent_fds[8] = status_pipe[0];
    tracked_parent_fds[9] = status_pipe[1];
    child = fork();
    if (child < 0) {
        goto setup_failure;
    }
    if (child == 0) {
        (void)close(input_pipe[1]);
        (void)close(output_pipe[0]);
        (void)close(error_pipe[0]);
        (void)close(status_pipe[0]);
        if (setpgid(0, 0) != 0 || dup2(input_pipe[0], STDIN_FILENO) < 0 ||
            dup2(output_pipe[1], STDOUT_FILENO) < 0 ||
            dup2(error_pipe[1], STDERR_FILENO) < 0 ||
            fchdir(run_anchor.leaf_fd) != 0 || w3_drop_irreversibly_to_runner() != 0 ||
            w3_close_child_fds(status_pipe[1]) != 0) {
            _exit(126);
        }
        {
            ssize_t reported;

            do {
                reported = write(status_pipe[1], &child_boundary_marker, 1U);
            } while (reported < 0 && errno == EINTR);
            if (reported != 1 || close(status_pipe[1]) != 0) {
                _exit(126);
            }
        }
        execve(W3_SANDBOX_EXEC_PATH, w3_child_argv, w3_child_environment);
        _exit(127);
    }

    (void)close(input_pipe[0]);
    input_pipe[0] = -1;
    (void)close(output_pipe[1]);
    output_pipe[1] = -1;
    (void)close(error_pipe[1]);
    error_pipe[1] = -1;
    (void)close(status_pipe[1]);
    status_pipe[1] = -1;
    input_open = 1;
    output_open = 1;
    error_open = 1;
    status_open = 1;
    if (setpgid(child, child) == 0) {
        group_established = 1;
    } else {
        int setpgid_error = errno;

        if (setpgid_error == EACCES) {
            pid_t observed_group = getpgid(child);

            if (observed_group == child) {
                group_established = 1;
            } else if (!(observed_group < 0 && errno == ESRCH)) {
                failure = 1;
            }
        } else if (setpgid_error != ESRCH) {
            failure = 1;
        }
    }
    if (w3_set_nonblocking(input_pipe[1]) != 0 ||
        w3_set_nonblocking(output_pipe[0]) != 0 ||
        w3_set_nonblocking(error_pipe[0]) != 0 ||
        w3_set_nonblocking(status_pipe[0]) != 0) {
        failure = 1;
    }
    deadline = w3_monotonic_milliseconds() + W3_EXECUTION_TIMEOUT_MS;

    while (!failure && (input_open || output_open || error_open || status_open)) {
        struct pollfd descriptors[4];
        nfds_t count = 0U;
        int remaining = w3_deadline_remaining(deadline);
        int poll_result;
        nfds_t index;

        if (remaining == 0) {
            timed_out = 1;
            break;
        }
        if (input_open) {
            descriptors[count] = (struct pollfd){.fd = input_pipe[1], .events = POLLOUT};
            ++count;
        }
        if (status_open) {
            descriptors[count] = (struct pollfd){.fd = status_pipe[0], .events = POLLIN};
            ++count;
        }
        if (output_open) {
            descriptors[count] = (struct pollfd){.fd = output_pipe[0], .events = POLLIN};
            ++count;
        }
        if (error_open) {
            descriptors[count] = (struct pollfd){.fd = error_pipe[0], .events = POLLIN};
            ++count;
        }
        if (remaining > 25) {
            remaining = 25;
        }
        poll_result = poll(descriptors, count, remaining);
        if (poll_result < 0 && errno != EINTR) {
            failure = 1;
            break;
        }
        if (poll_result > 0) {
            for (index = 0U; index < count; ++index) {
                short events = descriptors[index].revents;

                if (descriptors[index].fd == input_pipe[1] &&
                    (events & (POLLOUT | POLLERR | POLLHUP)) != 0) {
                    if ((events & POLLOUT) != 0 && input_offset < payload_length) {
                        ssize_t written = write(
                            input_pipe[1],
                            payload + input_offset,
                            payload_length - input_offset
                        );
                        if (written > 0) {
                            input_offset += (uint32_t)written;
                        } else if (written < 0 && errno == EPIPE) {
                            (void)close(input_pipe[1]);
                            input_pipe[1] = -1;
                            input_open = 0;
                        } else if (written < 0 && errno != EINTR && errno != EAGAIN &&
                                   errno != EWOULDBLOCK) {
                            failure = 1;
                        }
                    }
                    if (input_open &&
                        (input_offset == payload_length ||
                         (events & (POLLERR | POLLHUP)) != 0)) {
                        (void)close(input_pipe[1]);
                        input_pipe[1] = -1;
                        input_open = 0;
                    }
                } else if (descriptors[index].fd == output_pipe[0] &&
                           (events & (POLLIN | POLLERR | POLLHUP)) != 0) {
                    if (w3_append_output(
                            output_pipe[0],
                            result->stdout_bytes,
                            &result->stdout_length,
                            W3_MAX_STDOUT_BYTES,
                            &output_open
                        ) != 0) {
                        output_capped = errno == EFBIG;
                        failure = !output_capped;
                        break;
                    }
                    if (!output_open) {
                        output_pipe[0] = -1;
                    }
                } else if (descriptors[index].fd == error_pipe[0] &&
                           (events & (POLLIN | POLLERR | POLLHUP)) != 0) {
                    if (w3_append_output(
                            error_pipe[0],
                            result->stderr_bytes,
                            &result->stderr_length,
                            W3_MAX_STDERR_BYTES,
                            &error_open
                        ) != 0) {
                        output_capped = errno == EFBIG;
                        failure = !output_capped;
                        break;
                    }
                    if (!error_open) {
                        error_pipe[0] = -1;
                    }
                } else if (descriptors[index].fd == status_pipe[0] &&
                           (events & (POLLIN | POLLERR | POLLHUP)) != 0) {
                    uint8_t marker_bytes[2];
                    ssize_t marker_count;

                    do {
                        marker_count = read(status_pipe[0], marker_bytes, sizeof(marker_bytes));
                    } while (marker_count < 0 && errno == EINTR);
                    if (marker_count > 0) {
                        if (marker_count != 1 ||
                            marker_bytes[0] != child_boundary_marker ||
                            result->child_boundary_succeeded != 0U) {
                            failure = 1;
                            break;
                        }
                        result->child_boundary_succeeded = 1U;
                    } else if (marker_count == 0) {
                        (void)close(status_pipe[0]);
                        status_pipe[0] = -1;
                        status_open = 0;
                    } else if (errno != EAGAIN && errno != EWOULDBLOCK) {
                        failure = 1;
                        break;
                    }
                }
            }
        }
        if (output_capped) {
            break;
        }
    }

    if (input_open) {
        (void)close(input_pipe[1]);
        input_pipe[1] = -1;
    }
    if (output_open) {
        (void)close(output_pipe[0]);
        output_pipe[0] = -1;
    }
    if (error_open) {
        (void)close(error_pipe[0]);
        error_pipe[0] = -1;
    }
    if (status_open) {
        (void)close(status_pipe[0]);
        status_pipe[0] = -1;
    }
    result->process_group_residual = group_established
                                         ? w3_terminate_and_reap_group(
                                               child,
                                               &wait_status,
                                               &child_reaped
                                           )
                                         : w3_terminate_and_reap_pid(
                                               child,
                                               &wait_status,
                                               &child_reaped
                                           );
    result->wait_kind = child_reaped ? w3_wait_kind(wait_status) : W3_WAIT_UNAVAILABLE;
    result->wait_value = child_reaped ? w3_wait_value(wait_status) : 0U;
    if (result->wait_kind == W3_WAIT_EXITED) {
        result->flags |= W3_RESULT_EXITED;
    } else if (result->wait_kind == W3_WAIT_SIGNALED) {
        result->flags |= W3_RESULT_SIGNALED;
    }
    if (timed_out) {
        result->flags |= W3_RESULT_TIMED_OUT;
    }
    if (output_capped) {
        result->flags |= W3_RESULT_OUTPUT_CAPPED;
    }
    if (result->process_group_residual == 0U) {
        result->flags |= W3_RESULT_PROCESS_GROUP_ZERO;
    }
    {
        uint32_t first_temp_entries = w3_count_temp_entries_at(run_anchor.leaf_fd);
        uint32_t second_temp_entries;

        if (w3_reverify_run_root_anchor(&run_anchor) != 0) {
            first_temp_entries = UINT32_MAX;
        }
        second_temp_entries = w3_count_temp_entries_at(run_anchor.leaf_fd);
        if (w3_reverify_run_root_anchor(&run_anchor) != 0 ||
            first_temp_entries != second_temp_entries) {
            result->temp_entries = UINT32_MAX;
        } else {
            result->temp_entries = first_temp_entries;
        }
    }
    w3_close_run_root_anchor(&run_anchor);
    result->retained_fds = w3_count_retained_pipe_fds(tracked_parent_fds, 10U);
    w3_close_retained_pipe_fds(tracked_parent_fds, 10U);
    if (result->retained_fds == 0U) {
        result->flags |= W3_RESULT_FD_ZERO;
    }
    if (result->temp_entries == 0U) {
        result->flags |= W3_RESULT_TEMP_ZERO;
    }
    if (timed_out) {
        result->status = W3_LAUNCHER_STATUS_TIMED_OUT;
    } else if (output_capped) {
        result->status = W3_LAUNCHER_STATUS_OUTPUT_CAPPED;
    } else if (failure) {
        result->status = W3_LAUNCHER_STATUS_IO_FAILED;
    } else if (result->child_boundary_succeeded != 1U) {
        result->status = W3_LAUNCHER_STATUS_LAUNCH_FAILED;
    } else if (result->process_group_residual != 0U || result->retained_fds != 0U ||
               result->temp_entries != 0U) {
        result->status = W3_LAUNCHER_STATUS_CLEANUP_FAILED;
    } else if (result->wait_kind == W3_WAIT_UNAVAILABLE) {
        result->status = W3_LAUNCHER_STATUS_LAUNCH_FAILED;
    } else {
        result->status = W3_LAUNCHER_STATUS_COMPLETE;
    }
    w3_fill_cleanup_record(result);
    return 0;

setup_failure:
    if (input_pipe[0] >= 0) {
        (void)close(input_pipe[0]);
    }
    if (input_pipe[1] >= 0) {
        (void)close(input_pipe[1]);
    }
    if (output_pipe[0] >= 0) {
        (void)close(output_pipe[0]);
    }
    if (output_pipe[1] >= 0) {
        (void)close(output_pipe[1]);
    }
    if (error_pipe[0] >= 0) {
        (void)close(error_pipe[0]);
    }
    if (error_pipe[1] >= 0) {
        (void)close(error_pipe[1]);
    }
    if (status_pipe[0] >= 0) {
        (void)close(status_pipe[0]);
    }
    if (status_pipe[1] >= 0) {
        (void)close(status_pipe[1]);
    }
    w3_close_run_root_anchor(&run_anchor);
    w3_free_execution_result(result);
    return -1;
}
#endif

static int w3_build_result_payload(
    const struct w3_execution_result *result,
    uint8_t **payload_out,
    uint32_t *payload_length_out
)
{
    struct w3_launcher_result_header header;
    uint64_t total = sizeof(header) + (uint64_t)result->stdout_length +
                     (uint64_t)result->stderr_length + sizeof(result->cleanup);
    uint8_t *payload;
    size_t offset;

    if (total == 0U || total > W3_LAUNCHER_MAX_PAYLOAD_BYTES) {
        errno = EOVERFLOW;
        return -1;
    }
    payload = calloc((size_t)total, 1U);
    if (payload == NULL) {
        return -1;
    }
    memset(&header, 0, sizeof(header));
    memcpy(header.magic, W3_LAUNCHER_RESULT_MAGIC, W3_LAUNCHER_MAGIC_BYTES);
    header.version_be = htonl(W3_LAUNCHER_RESULT_VERSION);
    header.flags_be = htonl(result->flags);
    header.wait_kind_be = htonl(result->wait_kind);
    header.wait_value_be = htonl(result->wait_value);
    header.stdout_length_be = htonl(result->stdout_length);
    header.stderr_length_be = htonl(result->stderr_length);
    header.cleanup_length_be = htonl((uint32_t)sizeof(result->cleanup));
    memcpy(payload, &header, sizeof(header));
    offset = sizeof(header);
    memcpy(payload + offset, result->stdout_bytes, result->stdout_length);
    offset += result->stdout_length;
    memcpy(payload + offset, result->stderr_bytes, result->stderr_length);
    offset += result->stderr_length;
    memcpy(payload + offset, &result->cleanup, sizeof(result->cleanup));
    *payload_out = payload;
    *payload_length_out = (uint32_t)total;
    return 0;
}

static int w3_send_execution_response(
    int descriptor,
    const struct w3_launcher_request_header *request,
    const struct w3_execution_result *result
)
{
    struct w3_launcher_response_header response;
    uint8_t *payload = NULL;
    uint32_t payload_length = 0U;
    uint64_t deadline = w3_monotonic_milliseconds() + W3_FRAME_TIMEOUT_MS;
    int send_result;

    if (w3_build_result_payload(result, &payload, &payload_length) != 0) {
        return -1;
    }
    memset(&response, 0, sizeof(response));
    memcpy(response.magic, W3_LAUNCHER_MAGIC, W3_LAUNCHER_MAGIC_BYTES);
    response.version_be = htonl(W3_LAUNCHER_PROTOCOL_VERSION);
    response.status_be = htonl(result->status);
    response.payload_length_be = htonl(payload_length);
    memcpy(response.request_sha256, request->request_sha256, W3_SHA256_BYTES);
    memcpy(response.broker_nonce, request->broker_nonce, W3_NONCE_BYTES);
    if (CC_SHA256(
            &result->cleanup,
            (CC_LONG)sizeof(result->cleanup),
            response.cleanup_sha256
        ) == NULL) {
        free(payload);
        errno = EIO;
        return -1;
    }
    send_result = w3_send_exact(descriptor, &response, sizeof(response), deadline);
    if (send_result == 0) {
        send_result = w3_send_exact(descriptor, payload, payload_length, deadline);
    }
    memset(payload, 0, payload_length);
    free(payload);
    return send_result;
}

static int w3_serve_authenticated_connection(int descriptor)
{
    struct w3_request_frame frame;
    struct w3_execution_result result;
    uid_t broker_peer_uid = (uid_t)-1;
    gid_t broker_peer_gid = (gid_t)-1;
    int no_sigpipe = 1;
    int outcome = EX_SOFTWARE;

    memset(&frame, 0, sizeof(frame));
    memset(&result, 0, sizeof(result));
    if (!w3_configuration_is_frozen() ||
        setsockopt(descriptor, SOL_SOCKET, SO_NOSIGPIPE, &no_sigpipe, sizeof(no_sigpipe)) != 0 ||
        w3_authorize_broker_peer(descriptor, &broker_peer_uid, &broker_peer_gid) != 0 ||
        w3_receive_request_frame(descriptor, &frame) != 0) {
        return EX_NOPERM;
    }
#ifdef W3_PRIVILEGED_LAUNCHER_PHASE_B
    if (w3_phase_b_launch_registered_node(
            frame.payload,
            frame.payload_length,
            broker_peer_uid,
            broker_peer_gid,
            &result
        ) != 0) {
#else
    errno = ENOTSUP;
    if (1) {
#endif
        goto cleanup;
    }
    if (w3_send_execution_response(descriptor, &frame.header, &result) != 0) {
        goto cleanup;
    }
    outcome = EX_OK;

cleanup:
    w3_free_execution_result(&result);
    w3_free_request_frame(&frame);
    return outcome;
}

#ifdef W3_PRIVILEGED_LAUNCHER_PHASE_B
static int w3_run_accept_loop(int listener)
{
    for (;;) {
        int connection;

        do {
            connection = accept(listener, NULL, NULL);
        } while (connection < 0 && errno == EINTR);
        if (connection < 0) {
            return EX_OSERR;
        }
        if (w3_set_close_on_exec(connection, 1) != 0) {
            (void)close(connection);
            continue;
        }
        (void)w3_serve_authenticated_connection(connection);
        (void)shutdown(connection, SHUT_RDWR);
        (void)close(connection);
    }
}
#endif

int main(void)
{
    (void)w3_launch_registered_node;
    (void)w3_authorize_broker_peer_as;
    (void)w3_drop_with_ops;
    (void)w3_system_credential_ops;
#ifndef W3_PRIVILEGED_LAUNCHER_PHASE_B
    (void)w3_activate_listener_with;
    (void)w3_serve_authenticated_connection;
    (void)w3_child_argv;
    (void)w3_child_environment;
    (void)w3_set_nonblocking;
    (void)w3_prepare_supervisor_signal_policy;
    (void)w3_close_child_fds;
    (void)w3_drop_irreversibly_to_runner;
    (void)w3_make_pipe;
    (void)w3_same_file_identity;
    (void)w3_validate_seatbelt_policy;
    (void)w3_run_parent_metadata_is_valid;
    (void)w3_run_leaf_metadata_is_valid;
    (void)w3_close_run_root_anchor;
    (void)w3_reverify_run_root_anchor;
    (void)w3_open_run_root_anchor;
    (void)w3_count_temp_entries_at;
    (void)w3_wait_kind;
    (void)w3_wait_value;
    (void)w3_terminate_and_reap_pid;
    (void)w3_terminate_and_reap_group;
    (void)w3_count_retained_pipe_fds;
    (void)w3_close_retained_pipe_fds;
    (void)w3_append_output;
    (void)w3_fill_cleanup_record;
    fputs("w3 privileged launcher: transport not installed (Phase B disabled)\n", stderr);
    return EX_CONFIG;
#else
    int listener = -1;
    int outcome;

    if (!w3_configuration_is_frozen()) {
        fputs("w3 privileged launcher: installed configuration is not frozen\n", stderr);
        return EX_CONFIG;
    }
    if (w3_prepare_supervisor_signal_policy() != 0 ||
        w3_activate_listener_with(launch_activate_socket, &listener) != 0) {
        fputs("w3 privileged launcher: launchd activation failed\n", stderr);
        return EX_UNAVAILABLE;
    }
    outcome = w3_run_accept_loop(listener);
    (void)close(listener);
    return outcome;
#endif
}
