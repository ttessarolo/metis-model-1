/*
 * Metis Model 1 Phase-B native installer bootstrap.
 *
 * This program is only a post-materialization verifier and copier.  It cannot
 * establish trust in its own bytes.  A future authorized administrator must
 * compile from a trusted system copy, install both this binary and the closed
 * descriptor with trusted /usr/bin/install, and externally compare their
 * expected hashes before the first execution.  The checks below retain that
 * trust across path resolution, source races, copying and exec; they never
 * claim that code from a caller-writable checkout authenticated itself.
 * Because Mach-O loading precedes main(), the host invocation contract must
 * also enter through a trusted administrator boundary whose environment was
 * already scrubbed (and whose dyld/system-library provenance is bound).  The
 * in-main environment/identity/signal/FD normalization below is defense in
 * depth; it makes no claim about an already-compromised administrator context.
 *
 * Crash recovery never infers ownership from file shape.  The only mutable
 * tree is an atomically-created sibling whose fixed basename is suffixed by
 * the verified descriptor digest.  That digest-named directory is the durable
 * native intent marker.  It is locked, repaired only as a compatible subset,
 * and published to the fixed target with a no-replace rename.  An externally
 * created fixed target is never repaired or removed: it is either an exact
 * closed-tree match or a hard failure.
 *
 * L70 only syntax-checks and exercises this source with unprivileged temporary
 * fixtures.  It must never install, elevate, start services or execute the
 * real Python installer during this wave.
 */

#include <CommonCrypto/CommonDigest.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <libproc.h>
#include <limits.h>
#include <mach-o/dyld.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

extern char **environ;

#ifndef O_CLOEXEC
#define O_CLOEXEC 0
#endif

#ifndef O_NOFOLLOW
#define O_NOFOLLOW 0
#endif

#ifndef W3_BOOTSTRAP_TARGET
#define W3_BOOTSTRAP_TARGET "/private/var/db/MetisModel1/w3-installer-bootstrap"
#endif

#ifndef W3_BOOTSTRAP_DESCRIPTOR
#define W3_BOOTSTRAP_DESCRIPTOR \
    "/private/var/db/MetisModel1/w3-phase-b-bootstrap.descriptor"
#endif

#ifndef W3_BOOTSTRAP_SOURCE_ROOT
#define W3_BOOTSTRAP_SOURCE_ROOT \
    "/private/var/tmp/MetisModel1-w3-phase-b-source"
#endif

#ifndef W3_BOOTSTRAP_TARGET_ROOT
#define W3_BOOTSTRAP_TARGET_ROOT \
    "/private/var/db/MetisModel1/w3-phase-b-install-bundle"
#endif

#ifndef W3_BOOTSTRAP_PYTHON
#define W3_BOOTSTRAP_PYTHON W3_BOOTSTRAP_TARGET_ROOT "/" W3_BOOTSTRAP_PYTHON_RELATIVE
#endif

#ifndef W3_BOOTSTRAP_PYTHON_RELATIVE
#define W3_BOOTSTRAP_PYTHON_RELATIVE                                        \
    "install-root/Library/Application Support/MetisModel1/runtime/python"  \
    "/bin/python3.13"
#endif

#ifndef W3_BOOTSTRAP_EXECUTOR_RELATIVE
#define W3_BOOTSTRAP_EXECUTOR_RELATIVE                                      \
    "install-root/Library/Application Support/MetisModel1/runtime/python"  \
    "/lib/python3.13/site-packages/runtime/w3_broker_executor.py"
#endif

#ifndef W3_BOOTSTRAP_EXECUTOR_MODULE
#define W3_BOOTSTRAP_EXECUTOR_MODULE "runtime.w3_broker_executor"
#endif

#ifndef W3_BOOTSTRAP_REQUIRED_EUID
#define W3_BOOTSTRAP_REQUIRED_EUID ((uid_t)0)
#endif

#ifndef W3_BOOTSTRAP_TRUSTED_UID
#define W3_BOOTSTRAP_TRUSTED_UID ((uid_t)0)
#endif

#ifndef W3_BOOTSTRAP_TRUSTED_GID
#define W3_BOOTSTRAP_TRUSTED_GID ((gid_t)0)
#endif

#ifndef W3_BOOTSTRAP_EXECVE
#define W3_BOOTSTRAP_EXECVE execve
#endif

#ifndef W3_BOOTSTRAP_GET_EXECUTABLE_PATH
#define W3_BOOTSTRAP_GET_EXECUTABLE_PATH _NSGetExecutablePath
#endif

#ifndef W3_BOOTSTRAP_SETGROUPS
#define W3_BOOTSTRAP_SETGROUPS setgroups
#endif

#ifndef W3_BOOTSTRAP_SETGID
#define W3_BOOTSTRAP_SETGID setgid
#endif

#ifndef W3_BOOTSTRAP_SETUID
#define W3_BOOTSTRAP_SETUID setuid
#endif

#ifndef W3_BOOTSTRAP_GETGROUPS
#define W3_BOOTSTRAP_GETGROUPS getgroups
#endif

#ifndef W3_BOOTSTRAP_GETUID
#define W3_BOOTSTRAP_GETUID getuid
#endif

#ifndef W3_BOOTSTRAP_GETEUID
#define W3_BOOTSTRAP_GETEUID geteuid
#endif

#ifndef W3_BOOTSTRAP_GETGID
#define W3_BOOTSTRAP_GETGID getgid
#endif

#ifndef W3_BOOTSTRAP_GETEGID
#define W3_BOOTSTRAP_GETEGID getegid
#endif

#ifndef W3_BOOTSTRAP_SIGACTION
#define W3_BOOTSTRAP_SIGACTION sigaction
#endif

#ifndef W3_BOOTSTRAP_SIGPROCMASK
#define W3_BOOTSTRAP_SIGPROCMASK sigprocmask
#endif

#ifndef W3_BOOTSTRAP_SETRLIMIT
#define W3_BOOTSTRAP_SETRLIMIT setrlimit
#endif

#ifndef W3_BOOTSTRAP_GETRLIMIT
#define W3_BOOTSTRAP_GETRLIMIT getrlimit
#endif

#define W3_DESCRIPTOR_MAGIC "METIS-W3-PHASE-B-BOOTSTRAP-V1"
#define W3_DESCRIPTOR_MAX_BYTES (32U * 1024U * 1024U)
#define W3_MAX_FILES 8192U
#define W3_MAX_TOTAL_BYTES UINT64_C(2147483648)
#define W3_MAX_RELATIVE_PATH_BYTES 1024U
#define W3_MAX_TREE_DEPTH 256U
#define W3_SHA256_BYTES 32U
#define W3_SHA256_HEX_BYTES 64U
#define W3_COPY_BUFFER_BYTES (64U * 1024U)
#define W3_MAX_FD_CENSUS 65536U
#define W3_DESCRIPTOR_MODE ((mode_t)0444)
#define W3_BOOTSTRAP_MODE ((mode_t)0555)
#define W3_TARGET_ROOT_MODE ((mode_t)0700)
#define W3_TARGET_DIRECTORY_MODE ((mode_t)0755)
#define W3_METADATA_MANIFEST "metadata/w3-phase-b-install-bundle.json"
#define W3_METADATA_PLAN "metadata/install-plan.json"
#define W3_CANDIDATE_TAG ".candidate-"

#ifndef W3_BOOTSTRAP_TESTING
_Static_assert(W3_BOOTSTRAP_REQUIRED_EUID == (uid_t)0, "bootstrap must start as root");
_Static_assert(W3_BOOTSTRAP_TRUSTED_UID == (uid_t)0, "trusted owner must be root");
_Static_assert(W3_BOOTSTRAP_TRUSTED_GID == (gid_t)0, "trusted group must be wheel");
#endif

enum w3_fault_point {
    W3_FAULT_AFTER_CANDIDATE_ROOT = 1,
    W3_FAULT_MID_LEAF = 2,
    W3_FAULT_AFTER_PAYLOAD_COMPLETE = 3,
    W3_FAULT_AFTER_PUBLISH = 4,
};

#ifndef W3_BOOTSTRAP_FAULT
#define W3_BOOTSTRAP_FAULT(point) (0)
#endif

enum w3_status {
    W3_STATUS_OK = 0,
    W3_STATUS_USAGE = 64,
    W3_STATUS_CONTRACT = 70,
    W3_STATUS_EXEC = 71,
};

struct w3_leaf {
    int parent_fd;
    int fd;
    char name[NAME_MAX + 1U];
    struct stat initial;
};

struct w3_file_entry {
    char path[W3_MAX_RELATIVE_PATH_BYTES + 1U];
    uint64_t size;
    uint8_t sha256[W3_SHA256_BYTES];
    mode_t mode;
};

struct w3_descriptor {
    uint8_t bootstrap_sha256[W3_SHA256_BYTES];
    uint8_t manifest_sha256[W3_SHA256_BYTES];
    uint8_t plan_sha256[W3_SHA256_BYTES];
    size_t file_count;
    uint64_t total_bytes;
    struct w3_file_entry *files;
};

static int w3_fail(const char *code)
{
    (void)fprintf(stderr, "W3_BOOTSTRAP_%s\n", code);
    return W3_STATUS_CONTRACT;
}

static void w3_clear_process_environment(void)
{
    static char *empty_environment[] = {NULL};
    environ = empty_environment;
}

static int w3_normalize_process_state(void)
{
    gid_t required_group = W3_BOOTSTRAP_TRUSTED_GID;
    gid_t observed_group;
    struct sigaction action;
    sigset_t empty_mask;
    struct rlimit core_limit;
    struct rlimit observed_limit;
    int signal_number;

    if (W3_BOOTSTRAP_SETGROUPS(1, &required_group) != 0 ||
        W3_BOOTSTRAP_SETGID(W3_BOOTSTRAP_TRUSTED_GID) != 0 ||
        W3_BOOTSTRAP_SETUID(W3_BOOTSTRAP_TRUSTED_UID) != 0 ||
        W3_BOOTSTRAP_GETUID() != W3_BOOTSTRAP_TRUSTED_UID ||
        W3_BOOTSTRAP_GETEUID() != W3_BOOTSTRAP_TRUSTED_UID ||
        W3_BOOTSTRAP_GETGID() != W3_BOOTSTRAP_TRUSTED_GID ||
        W3_BOOTSTRAP_GETEGID() != W3_BOOTSTRAP_TRUSTED_GID ||
        W3_BOOTSTRAP_GETGROUPS(0, NULL) != 1 ||
        W3_BOOTSTRAP_GETGROUPS(1, &observed_group) != 1 ||
        observed_group != W3_BOOTSTRAP_TRUSTED_GID) {
        return -1;
    }
    (void)memset(&action, 0, sizeof(action));
    if (sigemptyset(&action.sa_mask) != 0) {
        return -1;
    }
    action.sa_handler = SIG_DFL;
    for (signal_number = 1; signal_number < NSIG; ++signal_number) {
        if (signal_number != SIGKILL && signal_number != SIGSTOP &&
            W3_BOOTSTRAP_SIGACTION(signal_number, &action, NULL) != 0) {
            return -1;
        }
    }
    if (sigemptyset(&empty_mask) != 0 ||
        W3_BOOTSTRAP_SIGPROCMASK(SIG_SETMASK, &empty_mask, NULL) != 0) {
        return -1;
    }
    core_limit.rlim_cur = 0;
    core_limit.rlim_max = 0;
    if (W3_BOOTSTRAP_SETRLIMIT(RLIMIT_CORE, &core_limit) != 0 ||
        W3_BOOTSTRAP_GETRLIMIT(RLIMIT_CORE, &observed_limit) != 0 ||
        observed_limit.rlim_cur != 0 || observed_limit.rlim_max != 0) {
        return -1;
    }
    return 0;
}

static int w3_close_fds_from(int lowfd)
{
    struct proc_fdinfo *entries = NULL;
    size_t capacity = W3_MAX_FD_CENSUS + 1U;
    size_t buffer_bytes;
    int bytes;
    size_t count;
    size_t index;
    int result = -1;

    if (lowfd < 0) {
        return -1;
    }
    if (capacity > SIZE_MAX / sizeof(*entries)) {
        return -1;
    }
    buffer_bytes = capacity * sizeof(*entries);
    if (buffer_bytes > INT_MAX) {
        return -1;
    }
    entries = calloc(capacity, sizeof(*entries));
    if (entries == NULL) {
        return -1;
    }
    bytes = proc_pidinfo(
        getpid(),
        PROC_PIDLISTFDS,
        0,
        entries,
        (int)buffer_bytes);
    if (bytes < 0 || (size_t)bytes >= buffer_bytes ||
        (size_t)bytes % sizeof(*entries) != 0U) {
        goto done;
    }
    count = (size_t)bytes / sizeof(*entries);
    for (index = 0U; index < count; ++index) {
        int fd = entries[index].proc_fd;
        if (fd >= lowfd && close(fd) != 0 && errno != EBADF) {
            goto done;
        }
    }
    (void)memset(entries, 0, buffer_bytes);
    bytes = proc_pidinfo(
        getpid(),
        PROC_PIDLISTFDS,
        0,
        entries,
        (int)buffer_bytes);
    if (bytes < 0 || (size_t)bytes >= buffer_bytes ||
        (size_t)bytes % sizeof(*entries) != 0U) {
        goto done;
    }
    count = (size_t)bytes / sizeof(*entries);
    for (index = 0U; index < count; ++index) {
        if (entries[index].proc_fd >= lowfd) {
            goto done;
        }
    }
    result = 0;
done:
    if (entries != NULL) {
        (void)memset(entries, 0, buffer_bytes);
        free(entries);
    }
    return result;
}

static int w3_same_identity(const struct stat *left, const struct stat *right)
{
    return left->st_dev == right->st_dev && left->st_ino == right->st_ino &&
        left->st_mode == right->st_mode && left->st_uid == right->st_uid &&
        left->st_gid == right->st_gid && left->st_nlink == right->st_nlink &&
        left->st_size == right->st_size &&
        left->st_mtimespec.tv_sec == right->st_mtimespec.tv_sec &&
        left->st_mtimespec.tv_nsec == right->st_mtimespec.tv_nsec &&
        left->st_ctimespec.tv_sec == right->st_ctimespec.tv_sec &&
        left->st_ctimespec.tv_nsec == right->st_ctimespec.tv_nsec;
}

static int w3_is_trusted_directory(const struct stat *info)
{
    int owner_ok;
#ifdef W3_BOOTSTRAP_TESTING
    owner_ok = info->st_uid == (uid_t)0 || info->st_uid == W3_BOOTSTRAP_TRUSTED_UID;
    if (S_ISDIR(info->st_mode) && info->st_uid == (uid_t)0 &&
        info->st_gid == (gid_t)0 &&
        (info->st_mode & (mode_t)07777) == (mode_t)01777) {
        return 1;
    }
#else
    owner_ok = info->st_uid == W3_BOOTSTRAP_TRUSTED_UID;
#endif
    return S_ISDIR(info->st_mode) && owner_ok && (info->st_mode & (mode_t)0022) == 0;
}

static int w3_component(const char *start, size_t length, char output[NAME_MAX + 1U])
{
    if (length == 0U || length > NAME_MAX ||
        (length == 1U && start[0] == '.') ||
        (length == 2U && start[0] == '.' && start[1] == '.')) {
        return -1;
    }
    (void)memcpy(output, start, length);
    output[length] = '\0';
    return 0;
}

static void w3_close_leaf(struct w3_leaf *leaf)
{
    if (leaf->fd >= 0) {
        (void)close(leaf->fd);
    }
    if (leaf->parent_fd >= 0) {
        (void)close(leaf->parent_fd);
    }
    leaf->fd = -1;
    leaf->parent_fd = -1;
}

static int w3_open_trusted_leaf(
    const char *path,
    uid_t expected_uid,
    gid_t expected_gid,
    mode_t expected_mode,
    struct w3_leaf *leaf)
{
    const char *cursor;
    int current = -1;
    int next = -1;
    struct stat info;

    (void)memset(leaf, 0, sizeof(*leaf));
    leaf->fd = -1;
    leaf->parent_fd = -1;
    if (path == NULL || path[0] != '/' || path[1] == '\0' || strstr(path, "//") != NULL) {
        return -1;
    }
    current = open("/", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (current < 0 || fstat(current, &info) != 0 || !w3_is_trusted_directory(&info)) {
        if (current >= 0) {
            (void)close(current);
        }
        return -1;
    }
    cursor = path + 1;
    for (;;) {
        const char *slash = strchr(cursor, '/');
        size_t length = slash == NULL ? strlen(cursor) : (size_t)(slash - cursor);
        char component[NAME_MAX + 1U];

        if (w3_component(cursor, length, component) != 0) {
            (void)close(current);
            return -1;
        }
        if (slash == NULL) {
            struct stat parent_info;
            if (length > NAME_MAX) {
                (void)close(current);
                return -1;
            }
            if (fstat(current, &parent_info) != 0 ||
                parent_info.st_uid != W3_BOOTSTRAP_TRUSTED_UID ||
                parent_info.st_gid != W3_BOOTSTRAP_TRUSTED_GID ||
                (parent_info.st_mode & (mode_t)07777) != (mode_t)0700) {
                (void)close(current);
                return -1;
            }
            (void)memcpy(leaf->name, component, length + 1U);
            leaf->fd = openat(current, component, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
            if (leaf->fd < 0 || fstat(leaf->fd, &leaf->initial) != 0 ||
                !S_ISREG(leaf->initial.st_mode) || leaf->initial.st_nlink != 1 ||
                leaf->initial.st_uid != expected_uid ||
                leaf->initial.st_gid != expected_gid ||
                (leaf->initial.st_mode & (mode_t)07777) != expected_mode) {
                if (leaf->fd >= 0) {
                    (void)close(leaf->fd);
                }
                (void)close(current);
                leaf->fd = -1;
                return -1;
            }
            leaf->parent_fd = current;
            return 0;
        }
        next = openat(current, component, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        if (next < 0 || fstat(next, &info) != 0 || !w3_is_trusted_directory(&info)) {
            if (next >= 0) {
                (void)close(next);
            }
            (void)close(current);
            return -1;
        }
        (void)close(current);
        current = next;
        next = -1;
        cursor = slash + 1;
    }
}

static int w3_postcheck_leaf(const struct w3_leaf *leaf)
{
    struct stat opened;
    struct stat named;

    if (fstat(leaf->fd, &opened) != 0 ||
        fstatat(leaf->parent_fd, leaf->name, &named, AT_SYMLINK_NOFOLLOW) != 0) {
        return -1;
    }
    return w3_same_identity(&leaf->initial, &opened) &&
        w3_same_identity(&leaf->initial, &named)
        ? 0
        : -1;
}

static int w3_hash_fd(
    int fd,
    uint64_t expected_size,
    uint8_t output[W3_SHA256_BYTES])
{
    CC_SHA256_CTX context;
    uint8_t buffer[W3_COPY_BUFFER_BYTES];
    uint64_t offset = 0U;

    if (CC_SHA256_Init(&context) != 1) {
        return -1;
    }
    while (offset < expected_size) {
        size_t wanted = sizeof(buffer);
        ssize_t count;
        if ((uint64_t)wanted > expected_size - offset) {
            wanted = (size_t)(expected_size - offset);
        }
        count = pread(fd, buffer, wanted, (off_t)offset);
        if (count <= 0 || (size_t)count > wanted ||
            CC_SHA256_Update(&context, buffer, (CC_LONG)count) != 1) {
            (void)memset(buffer, 0, sizeof(buffer));
            return -1;
        }
        offset += (uint64_t)count;
    }
    if (pread(fd, buffer, 1U, (off_t)offset) != 0 ||
        CC_SHA256_Final(output, &context) != 1) {
        (void)memset(buffer, 0, sizeof(buffer));
        return -1;
    }
    (void)memset(buffer, 0, sizeof(buffer));
    return 0;
}

static int w3_lower_hex_value(char character)
{
    if (character >= '0' && character <= '9') {
        return character - '0';
    }
    if (character >= 'a' && character <= 'f') {
        return character - 'a' + 10;
    }
    return -1;
}

static void w3_encode_digest_hex(
    const uint8_t digest[W3_SHA256_BYTES],
    char output[W3_SHA256_HEX_BYTES + 1U])
{
    static const char alphabet[] = "0123456789abcdef";
    size_t index;
    for (index = 0U; index < W3_SHA256_BYTES; ++index) {
        output[index * 2U] = alphabet[digest[index] >> 4U];
        output[index * 2U + 1U] = alphabet[digest[index] & 0x0fU];
    }
    output[W3_SHA256_HEX_BYTES] = '\0';
}

static int w3_decode_sha256(
    const char *text,
    size_t length,
    uint8_t output[W3_SHA256_BYTES])
{
    size_t index;
    if (length != W3_SHA256_HEX_BYTES) {
        return -1;
    }
    for (index = 0U; index < W3_SHA256_BYTES; ++index) {
        int high = w3_lower_hex_value(text[index * 2U]);
        int low = w3_lower_hex_value(text[index * 2U + 1U]);
        if (high < 0 || low < 0) {
            return -1;
        }
        output[index] = (uint8_t)((high << 4) | low);
    }
    return 0;
}

static int w3_prefixed_digest(
    const char *text,
    uint8_t output[W3_SHA256_BYTES])
{
    return text != NULL && strncmp(text, "sha256:", 7U) == 0 &&
        strlen(text) == 7U + W3_SHA256_HEX_BYTES
        ? w3_decode_sha256(text + 7U, W3_SHA256_HEX_BYTES, output)
        : -1;
}

static int w3_parse_decimal(
    const char *text,
    size_t length,
    uint64_t maximum,
    uint64_t *value)
{
    uint64_t result = 0U;
    size_t index;

    if (length == 0U || (length > 1U && text[0] == '0')) {
        return -1;
    }
    for (index = 0U; index < length; ++index) {
        unsigned int digit;
        if (text[index] < '0' || text[index] > '9') {
            return -1;
        }
        digit = (unsigned int)(text[index] - '0');
        if (result > (maximum - digit) / 10U) {
            return -1;
        }
        result = result * 10U + digit;
    }
    *value = result;
    return 0;
}

static int w3_valid_utf8(const uint8_t *bytes, size_t length)
{
    size_t index = 0U;
    while (index < length) {
        uint8_t first = bytes[index++];
        uint32_t codepoint;
        size_t continuation;
        size_t remaining;
        size_t offset;

        if (first < 0x80U) {
            if (first < 0x20U || first == 0x7fU) {
                return 0;
            }
            continue;
        }
        if (first >= 0xc2U && first <= 0xdfU) {
            codepoint = first & 0x1fU;
            continuation = 1U;
        } else if (first >= 0xe0U && first <= 0xefU) {
            codepoint = first & 0x0fU;
            continuation = 2U;
        } else if (first >= 0xf0U && first <= 0xf4U) {
            codepoint = first & 0x07U;
            continuation = 3U;
        } else {
            return 0;
        }
        remaining = length - index;
        if (remaining < continuation) {
            return 0;
        }
        for (offset = 0U; offset < continuation; ++offset) {
            uint8_t next = bytes[index++];
            if ((next & 0xc0U) != 0x80U) {
                return 0;
            }
            codepoint = (codepoint << 6U) | (uint32_t)(next & 0x3fU);
        }
        if ((continuation == 2U && (codepoint < 0x800U ||
                (codepoint >= 0xd800U && codepoint <= 0xdfffU))) ||
            (continuation == 3U && (codepoint < 0x10000U || codepoint > 0x10ffffU))) {
            return 0;
        }
    }
    return 1;
}

static int w3_valid_relative_path(const char *path, size_t length)
{
    size_t start = 0U;
    size_t index;

    if (length == 0U || length > W3_MAX_RELATIVE_PATH_BYTES || path[0] == '/' ||
        path[length - 1U] == '/' || !w3_valid_utf8((const uint8_t *)path, length)) {
        return 0;
    }
    for (index = 0U; index <= length; ++index) {
        if (index == length || path[index] == '/') {
            size_t component_length = index - start;
            if (component_length == 0U || component_length > NAME_MAX ||
                (component_length == 1U && path[start] == '.') ||
                (component_length == 2U && path[start] == '.' && path[start + 1U] == '.')) {
                return 0;
            }
            start = index + 1U;
        }
    }
    return 1;
}

static int w3_decode_path(
    const char *text,
    size_t length,
    char output[W3_MAX_RELATIVE_PATH_BYTES + 1U])
{
    size_t decoded_length;
    size_t index;

    if (length == 0U || (length & 1U) != 0U ||
        length > W3_MAX_RELATIVE_PATH_BYTES * 2U) {
        return -1;
    }
    decoded_length = length / 2U;
    for (index = 0U; index < decoded_length; ++index) {
        int high = w3_lower_hex_value(text[index * 2U]);
        int low = w3_lower_hex_value(text[index * 2U + 1U]);
        if (high < 0 || low < 0) {
            return -1;
        }
        output[index] = (char)((high << 4) | low);
        if (output[index] == '\0') {
            return -1;
        }
    }
    output[decoded_length] = '\0';
    return w3_valid_relative_path(output, decoded_length) ? 0 : -1;
}

static int w3_take_line(char **cursor, char *end, char **line, size_t *length)
{
    char *newline;
    if (*cursor >= end) {
        return -1;
    }
    newline = memchr(*cursor, '\n', (size_t)(end - *cursor));
    if (newline == NULL) {
        return -1;
    }
    *line = *cursor;
    *length = (size_t)(newline - *cursor);
    *newline = '\0';
    *cursor = newline + 1;
    return *length > 0U ? 0 : -1;
}

static int w3_header_value(
    char *line,
    size_t length,
    const char *key,
    char **value,
    size_t *value_length)
{
    size_t key_length = strlen(key);
    if (length <= key_length || memcmp(line, key, key_length) != 0 ||
        line[key_length] != '\t') {
        return -1;
    }
    *value = line + key_length + 1U;
    *value_length = length - key_length - 1U;
    return *value_length > 0U ? 0 : -1;
}

static int w3_split_file_row(char *line, size_t length, char *fields[5], size_t sizes[5])
{
    size_t field = 0U;
    size_t start = 0U;
    size_t index;
    for (index = 0U; index <= length; ++index) {
        if (index == length || line[index] == '\t') {
            if (field >= 5U || index == start) {
                return -1;
            }
            fields[field] = line + start;
            sizes[field] = index - start;
            if (index < length) {
                line[index] = '\0';
            }
            ++field;
            start = index + 1U;
        }
    }
    return field == 5U ? 0 : -1;
}

static void w3_free_descriptor(struct w3_descriptor *descriptor)
{
    if (descriptor->files != NULL) {
        (void)memset(
            descriptor->files,
            0,
            descriptor->file_count * sizeof(*descriptor->files));
        free(descriptor->files);
    }
    (void)memset(descriptor, 0, sizeof(*descriptor));
}

static int w3_parse_descriptor(
    char *payload,
    size_t payload_size,
    struct w3_descriptor *descriptor)
{
    char *cursor = payload;
    char *end = payload + payload_size;
    char *line;
    char *value;
    size_t length;
    size_t value_length;
    uint64_t parsed_count;
    uint64_t total = 0U;
    size_t index;
    int manifest_seen = 0;
    int plan_seen = 0;

    (void)memset(descriptor, 0, sizeof(*descriptor));
    if (payload_size == 0U || payload_size > W3_DESCRIPTOR_MAX_BYTES ||
        payload[payload_size - 1U] != '\n' ||
        memchr(payload, '\0', payload_size) != NULL ||
        memchr(payload, '\r', payload_size) != NULL ||
        w3_take_line(&cursor, end, &line, &length) != 0 ||
        length != strlen(W3_DESCRIPTOR_MAGIC) ||
        memcmp(line, W3_DESCRIPTOR_MAGIC, length) != 0) {
        return -1;
    }
#define W3_PARSE_HASH_HEADER(KEY, FIELD)                                      \
    do {                                                                      \
        if (w3_take_line(&cursor, end, &line, &length) != 0 ||               \
            w3_header_value(line, length, (KEY), &value, &value_length) != 0 || \
            w3_decode_sha256(value, value_length, (FIELD)) != 0) {            \
            return -1;                                                        \
        }                                                                     \
    } while (0)
    W3_PARSE_HASH_HEADER("bootstrap_sha256", descriptor->bootstrap_sha256);
    W3_PARSE_HASH_HEADER("manifest_sha256", descriptor->manifest_sha256);
    W3_PARSE_HASH_HEADER("plan_sha256", descriptor->plan_sha256);
#undef W3_PARSE_HASH_HEADER
    if (w3_take_line(&cursor, end, &line, &length) != 0 ||
        w3_header_value(line, length, "file_count", &value, &value_length) != 0 ||
        w3_parse_decimal(value, value_length, W3_MAX_FILES, &parsed_count) != 0 ||
        parsed_count == 0U) {
        return -1;
    }
    descriptor->file_count = (size_t)parsed_count;
    if (w3_take_line(&cursor, end, &line, &length) != 0 ||
        w3_header_value(line, length, "total_bytes", &value, &value_length) != 0 ||
        w3_parse_decimal(value, value_length, W3_MAX_TOTAL_BYTES, &descriptor->total_bytes) !=
            0 ||
        descriptor->total_bytes == 0U) {
        return -1;
    }
    descriptor->files = calloc(descriptor->file_count, sizeof(*descriptor->files));
    if (descriptor->files == NULL) {
        return -1;
    }
    for (index = 0U; index < descriptor->file_count; ++index) {
        char *fields[5];
        size_t sizes[5];
        uint64_t size;
        struct w3_file_entry *entry = &descriptor->files[index];

        if (w3_take_line(&cursor, end, &line, &length) != 0 ||
            w3_split_file_row(line, length, fields, sizes) != 0 || sizes[0] != 4U ||
            memcmp(fields[0], "FILE", 4U) != 0 ||
            w3_decode_path(fields[1], sizes[1], entry->path) != 0 ||
            w3_parse_decimal(fields[2], sizes[2], W3_MAX_TOTAL_BYTES, &size) != 0 ||
            w3_decode_sha256(fields[3], sizes[3], entry->sha256) != 0) {
            return -1;
        }
        if (sizes[4] == 4U && memcmp(fields[4], "0444", 4U) == 0) {
            entry->mode = (mode_t)0444;
        } else if (sizes[4] == 4U && memcmp(fields[4], "0555", 4U) == 0) {
            entry->mode = (mode_t)0555;
        } else {
            return -1;
        }
        entry->size = size;
        if (index > 0U &&
            strcmp(descriptor->files[index - 1U].path, entry->path) >= 0) {
            return -1;
        }
        if (total > W3_MAX_TOTAL_BYTES - size) {
            return -1;
        }
        total += size;
        if (strcmp(entry->path, W3_METADATA_MANIFEST) == 0) {
            if (manifest_seen ||
                memcmp(entry->sha256, descriptor->manifest_sha256, W3_SHA256_BYTES) != 0) {
                return -1;
            }
            manifest_seen = 1;
        }
        if (strcmp(entry->path, W3_METADATA_PLAN) == 0) {
            if (plan_seen ||
                memcmp(entry->sha256, descriptor->plan_sha256, W3_SHA256_BYTES) != 0) {
                return -1;
            }
            plan_seen = 1;
        }
    }
    if (cursor != end || total != descriptor->total_bytes || !manifest_seen || !plan_seen) {
        return -1;
    }
    return 0;
}

struct w3_root {
    int fd;
    int parent_fd;
    char name[NAME_MAX + 1U];
    struct stat initial;
};

static void w3_close_root(struct w3_root *root)
{
    if (root->fd >= 0) {
        (void)close(root->fd);
    }
    if (root->parent_fd >= 0) {
        (void)close(root->parent_fd);
    }
    root->fd = -1;
    root->parent_fd = -1;
}

static int w3_open_untrusted_source_root(struct w3_root *root)
{
    const char *cursor;
    int current = -1;
    struct stat named;
    struct stat opened;
    struct stat info;

    (void)memset(root, 0, sizeof(*root));
    root->fd = -1;
    root->parent_fd = -1;
    if (W3_BOOTSTRAP_SOURCE_ROOT[0] != '/' || W3_BOOTSTRAP_SOURCE_ROOT[1] == '\0' ||
        strstr(W3_BOOTSTRAP_SOURCE_ROOT, "//") != NULL) {
        return -1;
    }
    current = open("/", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (current < 0 || fstat(current, &info) != 0 || !w3_is_trusted_directory(&info)) {
        if (current >= 0) {
            (void)close(current);
        }
        return -1;
    }
    cursor = &W3_BOOTSTRAP_SOURCE_ROOT[1];
    for (;;) {
        const char *slash = strchr(cursor, '/');
        size_t length = slash == NULL ? strlen(cursor) : (size_t)(slash - cursor);
        char component[NAME_MAX + 1U];

        if (w3_component(cursor, length, component) != 0) {
            (void)close(current);
            return -1;
        }
        if (slash == NULL) {
            (void)memcpy(root->name, component, length + 1U);
            if (fstatat(current, component, &named, AT_SYMLINK_NOFOLLOW) != 0 ||
                !S_ISDIR(named.st_mode)) {
                (void)close(current);
                return -1;
            }
            root->fd = openat(
                current,
                component,
                O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
            if (root->fd < 0 || fstat(root->fd, &opened) != 0 ||
                !S_ISDIR(opened.st_mode) || opened.st_dev != named.st_dev ||
                opened.st_ino != named.st_ino) {
                if (root->fd >= 0) {
                    (void)close(root->fd);
                }
                (void)close(current);
                root->fd = -1;
                return -1;
            }
            root->initial = opened;
            root->parent_fd = current;
            return 0;
        }
        {
            int next = openat(
                current,
                component,
                O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
            int parent_ok;
            if (next < 0 || fstat(next, &info) != 0) {
                if (next >= 0) {
                    (void)close(next);
                }
                (void)close(current);
                return -1;
            }
#ifdef W3_BOOTSTRAP_TESTING
            parent_ok = w3_is_trusted_directory(&info) ||
                (S_ISDIR(info.st_mode) && info.st_uid == (uid_t)0 &&
                    info.st_gid == (gid_t)0 &&
                    (info.st_mode & (mode_t)07777) == (mode_t)01777);
#else
            int final_parent = strchr(slash + 1, '/') == NULL;
            parent_ok = final_parent
                ? S_ISDIR(info.st_mode) && info.st_uid == W3_BOOTSTRAP_TRUSTED_UID &&
                    info.st_gid == W3_BOOTSTRAP_TRUSTED_GID &&
                    (info.st_mode & (mode_t)07777) == (mode_t)01777
                : w3_is_trusted_directory(&info);
#endif
            if (!parent_ok) {
                (void)close(next);
                (void)close(current);
                return -1;
            }
            (void)close(current);
            current = next;
        }
        cursor = slash + 1;
    }
}

static int w3_postcheck_source_root(const struct w3_root *root)
{
    struct stat opened;
    struct stat named;
    return fstat(root->fd, &opened) == 0 &&
        fstatat(root->parent_fd, root->name, &named, AT_SYMLINK_NOFOLLOW) == 0 &&
        S_ISDIR(named.st_mode) && w3_same_identity(&root->initial, &opened) &&
        w3_same_identity(&root->initial, &named)
        ? 0
        : -1;
}

static int w3_open_trusted_parent(
    const char *path,
    int *parent_fd,
    char leaf_name[NAME_MAX + 1U])
{
    const char *cursor;
    int current = -1;
    struct stat info;

    *parent_fd = -1;
    if (path == NULL || path[0] != '/' || path[1] == '\0' || strstr(path, "//") != NULL) {
        return -1;
    }
    current = open("/", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (current < 0 || fstat(current, &info) != 0 || !w3_is_trusted_directory(&info)) {
        if (current >= 0) {
            (void)close(current);
        }
        return -1;
    }
    cursor = path + 1;
    for (;;) {
        const char *slash = strchr(cursor, '/');
        size_t length = slash == NULL ? strlen(cursor) : (size_t)(slash - cursor);
        char component[NAME_MAX + 1U];
        int next;

        if (w3_component(cursor, length, component) != 0) {
            (void)close(current);
            return -1;
        }
        if (slash == NULL) {
            (void)memcpy(leaf_name, component, length + 1U);
            *parent_fd = current;
            return 0;
        }
        next = openat(current, component, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        if (next < 0 || fstat(next, &info) != 0 || !w3_is_trusted_directory(&info)) {
            if (next >= 0) {
                (void)close(next);
            }
            (void)close(current);
            return -1;
        }
        (void)close(current);
        current = next;
        cursor = slash + 1;
    }
}

static int w3_open_fixed_target_root(struct w3_root *root)
{
    struct stat parent_info;
    struct stat named;

    (void)memset(root, 0, sizeof(*root));
    root->fd = -1;
    root->parent_fd = -1;
    if (w3_open_trusted_parent(
            W3_BOOTSTRAP_TARGET_ROOT,
            &root->parent_fd,
            root->name) != 0 ||
        fstat(root->parent_fd, &parent_info) != 0 ||
        parent_info.st_uid != W3_BOOTSTRAP_TRUSTED_UID ||
        parent_info.st_gid != W3_BOOTSTRAP_TRUSTED_GID ||
        (parent_info.st_mode & (mode_t)07777) != (mode_t)0700) {
        w3_close_root(root);
        return -1;
    }
    if (fstatat(root->parent_fd, root->name, &named, AT_SYMLINK_NOFOLLOW) != 0) {
        int missing = errno == ENOENT;
        w3_close_root(root);
        return missing ? 1 : -1;
    }
    if (!S_ISDIR(named.st_mode) ||
        named.st_uid != W3_BOOTSTRAP_TRUSTED_UID ||
        named.st_gid != W3_BOOTSTRAP_TRUSTED_GID ||
        (named.st_mode & (mode_t)07777) != W3_TARGET_ROOT_MODE) {
        w3_close_root(root);
        return -1;
    }
    root->fd = openat(
        root->parent_fd,
        root->name,
        O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (root->fd < 0 || fstat(root->fd, &root->initial) != 0 ||
        fstatat(root->parent_fd, root->name, &named, AT_SYMLINK_NOFOLLOW) != 0 ||
        !S_ISDIR(root->initial.st_mode) ||
        root->initial.st_uid != W3_BOOTSTRAP_TRUSTED_UID ||
        root->initial.st_gid != W3_BOOTSTRAP_TRUSTED_GID ||
        (root->initial.st_mode & (mode_t)07777) != W3_TARGET_ROOT_MODE ||
        root->initial.st_dev != named.st_dev || root->initial.st_ino != named.st_ino ||
        flock(root->fd, LOCK_SH | LOCK_NB) != 0) {
        w3_close_root(root);
        return -1;
    }
    return 0;
}

static int w3_build_candidate_name(
    const char *target_name,
    const uint8_t descriptor_digest[W3_SHA256_BYTES],
    char output[NAME_MAX + 1U])
{
    char digest_hex[W3_SHA256_HEX_BYTES + 1U];
    size_t target_length = strlen(target_name);
    size_t tag_length = strlen(W3_CANDIDATE_TAG);

    if (target_length == 0U ||
        target_length + tag_length + W3_SHA256_HEX_BYTES > NAME_MAX) {
        return -1;
    }
    w3_encode_digest_hex(descriptor_digest, digest_hex);
    (void)memcpy(output, target_name, target_length);
    (void)memcpy(output + target_length, W3_CANDIDATE_TAG, tag_length);
    (void)memcpy(
        output + target_length + tag_length,
        digest_hex,
        W3_SHA256_HEX_BYTES + 1U);
    (void)memset(digest_hex, 0, sizeof(digest_hex));
    return 0;
}

static int w3_open_or_create_candidate_root(
    const uint8_t descriptor_digest[W3_SHA256_BYTES],
    struct w3_root *root,
    int *created)
{
    char target_name[NAME_MAX + 1U];
    struct stat parent_info;
    struct stat named;
    int exists;

    (void)memset(root, 0, sizeof(*root));
    root->fd = -1;
    root->parent_fd = -1;
    *created = 0;
    if (w3_open_trusted_parent(
            W3_BOOTSTRAP_TARGET_ROOT,
            &root->parent_fd,
            target_name) != 0 ||
        fstat(root->parent_fd, &parent_info) != 0 ||
        parent_info.st_uid != W3_BOOTSTRAP_TRUSTED_UID ||
        parent_info.st_gid != W3_BOOTSTRAP_TRUSTED_GID ||
        (parent_info.st_mode & (mode_t)07777) != (mode_t)0700) {
        w3_close_root(root);
        return -1;
    }
    if (w3_build_candidate_name(target_name, descriptor_digest, root->name) != 0) {
        w3_close_root(root);
        return -1;
    }

    exists = fstatat(root->parent_fd, root->name, &named, AT_SYMLINK_NOFOLLOW) == 0;
    if (!exists) {
        if (errno != ENOENT ||
            mkdirat(root->parent_fd, root->name, W3_TARGET_ROOT_MODE) != 0) {
            w3_close_root(root);
            return -1;
        }
        *created = 1;
    } else if (!S_ISDIR(named.st_mode) ||
        named.st_uid != W3_BOOTSTRAP_TRUSTED_UID ||
        named.st_gid != W3_BOOTSTRAP_TRUSTED_GID ||
        (named.st_mode & (mode_t)07777) != W3_TARGET_ROOT_MODE) {
        w3_close_root(root);
        return -1;
    }
    root->fd = openat(
        root->parent_fd,
        root->name,
        O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (root->fd < 0 ||
        (*created &&
            (fchown(
                 root->fd,
                 W3_BOOTSTRAP_TRUSTED_UID,
                 W3_BOOTSTRAP_TRUSTED_GID) != 0 ||
                fchmod(root->fd, W3_TARGET_ROOT_MODE) != 0)) ||
        fsync(root->fd) != 0 || fsync(root->parent_fd) != 0 ||
        fstat(root->fd, &root->initial) != 0 ||
        fstatat(root->parent_fd, root->name, &named, AT_SYMLINK_NOFOLLOW) != 0 ||
        !S_ISDIR(root->initial.st_mode) ||
        root->initial.st_uid != W3_BOOTSTRAP_TRUSTED_UID ||
        root->initial.st_gid != W3_BOOTSTRAP_TRUSTED_GID ||
        (root->initial.st_mode & (mode_t)07777) != W3_TARGET_ROOT_MODE ||
        root->initial.st_dev != named.st_dev || root->initial.st_ino != named.st_ino ||
        flock(root->fd, LOCK_EX | LOCK_NB) != 0) {
        w3_close_root(root);
        return -1;
    }
    return 0;
}

static int w3_is_digest_named_candidate(
    const struct w3_root *root,
    const uint8_t descriptor_digest[W3_SHA256_BYTES])
{
    const char *target_name = strrchr(W3_BOOTSTRAP_TARGET_ROOT, '/');
    char expected[NAME_MAX + 1U];
    int matches = 0;

    if (target_name == NULL || target_name[1] == '\0') {
        return 0;
    }
    ++target_name;
    if (w3_build_candidate_name(target_name, descriptor_digest, expected) != 0) {
        return 0;
    }
    matches = strcmp(root->name, expected) == 0;
    (void)memset(expected, 0, sizeof(expected));
    return matches;
}

static int w3_census_candidate_namespace(
    const uint8_t descriptor_digest[W3_SHA256_BYTES],
    int *expected_exists)
{
    int parent_fd = -1;
    int verified_parent_fd = -1;
    int scan_fd = -1;
    DIR *stream = NULL;
    struct dirent *item;
    char target_name[NAME_MAX + 1U];
    char verified_target_name[NAME_MAX + 1U];
    char expected_name[NAME_MAX + 1U];
    char prefix[NAME_MAX + 1U];
    struct stat parent_before;
    struct stat parent_after;
    size_t prefix_length;
    int found = 0;
    int result = -1;

    *expected_exists = 0;
    if (w3_open_trusted_parent(
            W3_BOOTSTRAP_TARGET_ROOT,
            &parent_fd,
            target_name) != 0 ||
        fstat(parent_fd, &parent_before) != 0 ||
        parent_before.st_uid != W3_BOOTSTRAP_TRUSTED_UID ||
        parent_before.st_gid != W3_BOOTSTRAP_TRUSTED_GID ||
        (parent_before.st_mode & (mode_t)07777) != (mode_t)0700 ||
        w3_build_candidate_name(target_name, descriptor_digest, expected_name) != 0) {
        goto done;
    }
    prefix_length = strlen(target_name) + strlen(W3_CANDIDATE_TAG);
    if (prefix_length > NAME_MAX) {
        goto done;
    }
    (void)memcpy(prefix, target_name, strlen(target_name));
    (void)memcpy(
        prefix + strlen(target_name),
        W3_CANDIDATE_TAG,
        strlen(W3_CANDIDATE_TAG) + 1U);
    scan_fd = openat(
        parent_fd,
        ".",
        O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (scan_fd < 0) {
        goto done;
    }
    stream = fdopendir(scan_fd);
    if (stream == NULL) {
        goto done;
    }
    scan_fd = -1;
    errno = 0;
    while ((item = readdir(stream)) != NULL) {
        if (strncmp(item->d_name, prefix, prefix_length) == 0) {
            struct stat info;
            if (found || strcmp(item->d_name, expected_name) != 0 ||
                fstatat(parent_fd, item->d_name, &info, AT_SYMLINK_NOFOLLOW) != 0 ||
                !S_ISDIR(info.st_mode) || info.st_uid != W3_BOOTSTRAP_TRUSTED_UID ||
                info.st_gid != W3_BOOTSTRAP_TRUSTED_GID ||
                (info.st_mode & (mode_t)07777) != W3_TARGET_ROOT_MODE) {
                goto done;
            }
            found = 1;
        }
        errno = 0;
    }
    if (errno != 0 || closedir(stream) != 0) {
        stream = NULL;
        goto done;
    }
    stream = NULL;
    if (w3_open_trusted_parent(
            W3_BOOTSTRAP_TARGET_ROOT,
            &verified_parent_fd,
            verified_target_name) != 0 ||
        strcmp(target_name, verified_target_name) != 0 ||
        fstat(verified_parent_fd, &parent_after) != 0 ||
        parent_before.st_dev != parent_after.st_dev ||
        parent_before.st_ino != parent_after.st_ino) {
        goto done;
    }
    *expected_exists = found;
    result = 0;
done:
    if (stream != NULL) {
        (void)closedir(stream);
    } else if (scan_fd >= 0) {
        (void)close(scan_fd);
    }
    if (verified_parent_fd >= 0) {
        (void)close(verified_parent_fd);
    }
    if (parent_fd >= 0) {
        (void)close(parent_fd);
    }
    (void)memset(expected_name, 0, sizeof(expected_name));
    (void)memset(prefix, 0, sizeof(prefix));
    return result;
}

static int w3_postcheck_target_root(const struct w3_root *root)
{
    struct stat opened;
    struct stat named;
    if (fstat(root->fd, &opened) != 0 ||
        fstatat(root->parent_fd, root->name, &named, AT_SYMLINK_NOFOLLOW) != 0 ||
        !S_ISDIR(opened.st_mode) || opened.st_uid != W3_BOOTSTRAP_TRUSTED_UID ||
        opened.st_gid != W3_BOOTSTRAP_TRUSTED_GID ||
        (opened.st_mode & (mode_t)07777) != W3_TARGET_ROOT_MODE ||
        opened.st_dev != root->initial.st_dev || opened.st_ino != root->initial.st_ino ||
        opened.st_dev != named.st_dev || opened.st_ino != named.st_ino ||
        named.st_uid != W3_BOOTSTRAP_TRUSTED_UID ||
        named.st_gid != W3_BOOTSTRAP_TRUSTED_GID ||
        (named.st_mode & (mode_t)07777) != W3_TARGET_ROOT_MODE) {
        return -1;
    }
    return 0;
}

static ssize_t w3_find_entry(const struct w3_descriptor *descriptor, const char *path)
{
    size_t low = 0U;
    size_t high = descriptor->file_count;
    while (low < high) {
        size_t middle = low + (high - low) / 2U;
        int order = strcmp(path, descriptor->files[middle].path);
        if (order == 0) {
            return (ssize_t)middle;
        }
        if (order < 0) {
            high = middle;
        } else {
            low = middle + 1U;
        }
    }
    return -1;
}

static int w3_join_path(
    const char *prefix,
    const char *name,
    char output[W3_MAX_RELATIVE_PATH_BYTES + 1U])
{
    size_t prefix_length = strlen(prefix);
    size_t name_length = strlen(name);
    size_t total = prefix_length + (prefix_length == 0U ? 0U : 1U) + name_length;
    if (total == 0U || total > W3_MAX_RELATIVE_PATH_BYTES) {
        return -1;
    }
    if (prefix_length != 0U) {
        (void)memcpy(output, prefix, prefix_length);
        output[prefix_length] = '/';
        (void)memcpy(output + prefix_length + 1U, name, name_length + 1U);
    } else {
        (void)memcpy(output, name, name_length + 1U);
    }
    return w3_valid_relative_path(output, total) ? 0 : -1;
}

static int w3_verify_scanned_file(
    int parent_fd,
    const char *name,
    const struct stat *named_before,
    const struct w3_file_entry *entry,
    int trusted,
    int hash_content)
{
    int fd = -1;
    struct stat opened;
    struct stat final;
    struct stat named_after;
    uint8_t digest[W3_SHA256_BYTES];
    int result = -1;

    if (!S_ISREG(named_before->st_mode) || named_before->st_nlink != 1 ||
        named_before->st_size < 0 || (uint64_t)named_before->st_size != entry->size ||
        (named_before->st_mode & (mode_t)07777) != entry->mode ||
        (trusted && (named_before->st_uid != W3_BOOTSTRAP_TRUSTED_UID ||
            named_before->st_gid != W3_BOOTSTRAP_TRUSTED_GID))) {
        return -1;
    }
    fd = openat(parent_fd, name, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0 || fstat(fd, &opened) != 0 ||
        !w3_same_identity(named_before, &opened)) {
        goto done;
    }
    if (hash_content &&
        (w3_hash_fd(fd, entry->size, digest) != 0 ||
            memcmp(digest, entry->sha256, W3_SHA256_BYTES) != 0)) {
        goto done;
    }
    if ((trusted && hash_content && fsync(fd) != 0) || fstat(fd, &final) != 0 ||
        fstatat(parent_fd, name, &named_after, AT_SYMLINK_NOFOLLOW) != 0 ||
        !w3_same_identity(&opened, &final) || !w3_same_identity(&opened, &named_after)) {
        goto done;
    }
    result = 0;
done:
    (void)memset(digest, 0, sizeof(digest));
    if (fd >= 0) {
        (void)close(fd);
    }
    return result;
}

static int w3_scan_directory(
    int directory_fd,
    const char *prefix,
    unsigned int depth,
    const struct w3_descriptor *descriptor,
    uint8_t *seen,
    int trusted,
    int hash_content,
    size_t *files_found)
{
    DIR *stream = NULL;
    int scan_fd = -1;
    struct dirent *item;
    size_t local_files = 0U;
    int result = -1;

    if (depth > W3_MAX_TREE_DEPTH) {
        return -1;
    }
    scan_fd = openat(
        directory_fd,
        ".",
        O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (scan_fd < 0) {
        return -1;
    }
    stream = fdopendir(scan_fd);
    if (stream == NULL) {
        (void)close(scan_fd);
        return -1;
    }
    scan_fd = -1;
    errno = 0;
    while ((item = readdir(stream)) != NULL) {
        char path[W3_MAX_RELATIVE_PATH_BYTES + 1U];
        struct stat info;

        if (strcmp(item->d_name, ".") == 0 || strcmp(item->d_name, "..") == 0) {
            errno = 0;
            continue;
        }
        if (w3_join_path(prefix, item->d_name, path) != 0 ||
            fstatat(directory_fd, item->d_name, &info, AT_SYMLINK_NOFOLLOW) != 0) {
            goto done;
        }
        if (S_ISREG(info.st_mode)) {
            ssize_t entry_index = w3_find_entry(descriptor, path);
            if (entry_index < 0 || seen[(size_t)entry_index] != 0U ||
                w3_verify_scanned_file(
                    directory_fd,
                    item->d_name,
                    &info,
                    &descriptor->files[(size_t)entry_index],
                    trusted,
                    hash_content) != 0) {
                goto done;
            }
            seen[(size_t)entry_index] = 1U;
            ++local_files;
        } else if (S_ISDIR(info.st_mode)) {
            int child = openat(
                directory_fd,
                item->d_name,
                O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
            struct stat opened;
            struct stat final;
            struct stat named_after;
            size_t child_files = 0U;
            if (child < 0 || fstat(child, &opened) != 0 ||
                opened.st_dev != info.st_dev || opened.st_ino != info.st_ino ||
                (trusted && (!S_ISDIR(opened.st_mode) ||
                    opened.st_uid != W3_BOOTSTRAP_TRUSTED_UID ||
                    opened.st_gid != W3_BOOTSTRAP_TRUSTED_GID ||
                    (opened.st_mode & (mode_t)07777) != W3_TARGET_DIRECTORY_MODE)) ||
                w3_scan_directory(
                    child,
                    path,
                    depth + 1U,
                    descriptor,
                    seen,
                    trusted,
                    hash_content,
                    &child_files) != 0 ||
                child_files == 0U || (trusted && fsync(child) != 0) ||
                fstat(child, &final) != 0 ||
                fstatat(directory_fd, item->d_name, &named_after, AT_SYMLINK_NOFOLLOW) != 0 ||
                !w3_same_identity(&opened, &final) ||
                opened.st_dev != named_after.st_dev || opened.st_ino != named_after.st_ino) {
                if (child >= 0) {
                    (void)close(child);
                }
                goto done;
            }
            (void)close(child);
            local_files += child_files;
        } else {
            goto done;
        }
        errno = 0;
    }
    if (errno != 0) {
        goto done;
    }
    *files_found = local_files;
    result = 0;
done:
    if (stream != NULL) {
        (void)closedir(stream);
    } else if (scan_fd >= 0) {
        (void)close(scan_fd);
    }
    return result;
}

static int w3_scan_tree(
    int root_fd,
    const struct w3_descriptor *descriptor,
    int trusted,
    int hash_content)
{
    uint8_t *seen = calloc(descriptor->file_count, sizeof(*seen));
    size_t files_found = 0U;
    size_t index;
    int result = -1;

    if (seen == NULL ||
        w3_scan_directory(
            root_fd,
            "",
            0U,
            descriptor,
            seen,
            trusted,
            hash_content,
            &files_found) != 0 ||
        files_found != descriptor->file_count) {
        goto done;
    }
    for (index = 0U; index < descriptor->file_count; ++index) {
        if (seen[index] != 1U) {
            goto done;
        }
    }
    result = 0;
done:
    if (seen != NULL) {
        (void)memset(seen, 0, descriptor->file_count);
        free(seen);
    }
    return result;
}

static int w3_is_expected_directory(
    const struct w3_descriptor *descriptor,
    const char *path)
{
    size_t low = 0U;
    size_t high = descriptor->file_count;
    size_t path_length = strlen(path);

    while (low < high) {
        size_t middle = low + (high - low) / 2U;
        if (strcmp(descriptor->files[middle].path, path) < 0) {
            low = middle + 1U;
        } else {
            high = middle;
        }
    }
    return low < descriptor->file_count &&
        strncmp(descriptor->files[low].path, path, path_length) == 0 &&
        descriptor->files[low].path[path_length] == '/';
}

static int w3_verify_resumable_file(
    int parent_fd,
    const char *name,
    const struct stat *named_before,
    const struct w3_file_entry *entry,
    int *complete)
{
    int fd = -1;
    struct stat opened;
    struct stat final;
    struct stat named_after;
    uint8_t digest[W3_SHA256_BYTES];
    mode_t actual_mode = named_before->st_mode & (mode_t)07777;
    mode_t transitional_mode = entry->mode & (mode_t)0700;
    int exact_mode = actual_mode == entry->mode;
    int result = -1;

    *complete = 0;
    if (!S_ISREG(named_before->st_mode) || named_before->st_nlink != 1 ||
        named_before->st_uid != W3_BOOTSTRAP_TRUSTED_UID ||
        named_before->st_gid != W3_BOOTSTRAP_TRUSTED_GID ||
        (!exact_mode &&
            (actual_mode != transitional_mode || named_before->st_size != 0)) ||
        named_before->st_size < 0 ||
        (uint64_t)named_before->st_size > entry->size) {
        return -1;
    }
    fd = openat(parent_fd, name, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0 || fstat(fd, &opened) != 0 ||
        !w3_same_identity(named_before, &opened)) {
        goto done;
    }
    if (exact_mode && (uint64_t)opened.st_size == entry->size) {
        if (w3_hash_fd(fd, entry->size, digest) != 0 ||
            memcmp(digest, entry->sha256, W3_SHA256_BYTES) != 0) {
            goto done;
        }
        *complete = 1;
    }
    if (fstat(fd, &final) != 0 ||
        fstatat(parent_fd, name, &named_after, AT_SYMLINK_NOFOLLOW) != 0 ||
        !w3_same_identity(&opened, &final) || !w3_same_identity(&opened, &named_after)) {
        *complete = 0;
        goto done;
    }
    result = 0;
done:
    (void)memset(digest, 0, sizeof(digest));
    if (fd >= 0) {
        (void)close(fd);
    }
    return result;
}

static int w3_scan_resumable_directory(
    int directory_fd,
    const char *prefix,
    unsigned int depth,
    const struct w3_descriptor *descriptor,
    size_t *files_found,
    int *all_complete)
{
    DIR *stream = NULL;
    int scan_fd = -1;
    struct dirent *item;
    int result = -1;

    if (depth > W3_MAX_TREE_DEPTH) {
        return -1;
    }
    scan_fd = openat(
        directory_fd,
        ".",
        O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (scan_fd < 0) {
        return -1;
    }
    stream = fdopendir(scan_fd);
    if (stream == NULL) {
        (void)close(scan_fd);
        return -1;
    }
    scan_fd = -1;
    errno = 0;
    while ((item = readdir(stream)) != NULL) {
        char path[W3_MAX_RELATIVE_PATH_BYTES + 1U];
        struct stat info;

        if (strcmp(item->d_name, ".") == 0 || strcmp(item->d_name, "..") == 0) {
            errno = 0;
            continue;
        }
        if (w3_join_path(prefix, item->d_name, path) != 0 ||
            fstatat(directory_fd, item->d_name, &info, AT_SYMLINK_NOFOLLOW) != 0) {
            goto done;
        }
        if (S_ISREG(info.st_mode)) {
            ssize_t entry_index = w3_find_entry(descriptor, path);
            int complete;
            if (entry_index < 0 ||
                w3_verify_resumable_file(
                    directory_fd,
                    item->d_name,
                    &info,
                    &descriptor->files[(size_t)entry_index],
                    &complete) != 0) {
                goto done;
            }
            ++(*files_found);
            if (!complete) {
                *all_complete = 0;
            }
        } else if (S_ISDIR(info.st_mode) && w3_is_expected_directory(descriptor, path)) {
            int child = openat(
                directory_fd,
                item->d_name,
                O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
            struct stat opened;
            struct stat final;
            struct stat named_after;
            if (child < 0 || fstat(child, &opened) != 0 ||
                opened.st_dev != info.st_dev || opened.st_ino != info.st_ino ||
                opened.st_uid != W3_BOOTSTRAP_TRUSTED_UID ||
                opened.st_gid != W3_BOOTSTRAP_TRUSTED_GID ||
                ((opened.st_mode & (mode_t)07777) != W3_TARGET_DIRECTORY_MODE &&
                    (opened.st_mode & (mode_t)07777) != W3_TARGET_ROOT_MODE) ||
                w3_scan_resumable_directory(
                    child,
                    path,
                    depth + 1U,
                    descriptor,
                    files_found,
                    all_complete) != 0 ||
                fstat(child, &final) != 0 ||
                fstatat(directory_fd, item->d_name, &named_after, AT_SYMLINK_NOFOLLOW) != 0 ||
                !w3_same_identity(&opened, &final) ||
                !w3_same_identity(&opened, &named_after)) {
                if (child >= 0) {
                    (void)close(child);
                }
                goto done;
            }
            (void)close(child);
        } else {
            goto done;
        }
        errno = 0;
    }
    if (errno != 0) {
        goto done;
    }
    result = 0;
done:
    if (stream != NULL) {
        (void)closedir(stream);
    } else if (scan_fd >= 0) {
        (void)close(scan_fd);
    }
    return result;
}

static int w3_scan_resumable_tree(
    int root_fd,
    const struct w3_descriptor *descriptor,
    int *complete)
{
    size_t files_found = 0U;
    int all_complete = 1;

    if (w3_scan_resumable_directory(
            root_fd,
            "",
            0U,
            descriptor,
            &files_found,
            &all_complete) != 0 ||
        files_found > descriptor->file_count) {
        return -1;
    }
    *complete = all_complete && files_found == descriptor->file_count;
    return 0;
}

static int w3_open_relative_source_leaf(
    int root_fd,
    const struct w3_file_entry *entry,
    struct w3_leaf *leaf)
{
    char path[W3_MAX_RELATIVE_PATH_BYTES + 1U];
    char *cursor;
    int current = -1;

    (void)memset(leaf, 0, sizeof(*leaf));
    leaf->fd = -1;
    leaf->parent_fd = -1;
    (void)memcpy(path, entry->path, strlen(entry->path) + 1U);
    current = openat(root_fd, ".", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (current < 0) {
        return -1;
    }
    cursor = path;
    for (;;) {
        char *slash = strchr(cursor, '/');
        if (slash == NULL) {
            size_t name_length = strlen(cursor);
            struct stat named;
            if (name_length == 0U || name_length > NAME_MAX) {
                (void)close(current);
                return -1;
            }
            (void)memcpy(leaf->name, cursor, name_length + 1U);
            leaf->fd = openat(current, cursor, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
            if (leaf->fd < 0 || fstat(leaf->fd, &leaf->initial) != 0 ||
                fstatat(current, cursor, &named, AT_SYMLINK_NOFOLLOW) != 0 ||
                !S_ISREG(leaf->initial.st_mode) || leaf->initial.st_nlink != 1 ||
                leaf->initial.st_size < 0 ||
                (uint64_t)leaf->initial.st_size != entry->size ||
                (leaf->initial.st_mode & (mode_t)07777) != entry->mode ||
                !w3_same_identity(&leaf->initial, &named)) {
                if (leaf->fd >= 0) {
                    (void)close(leaf->fd);
                }
                (void)close(current);
                leaf->fd = -1;
                return -1;
            }
            leaf->parent_fd = current;
            return 0;
        }
        *slash = '\0';
        {
            int next = openat(
                current,
                cursor,
                O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
            if (next < 0) {
                (void)close(current);
                return -1;
            }
            (void)close(current);
            current = next;
        }
        cursor = slash + 1;
    }
}

static int w3_open_target_parent(
    int root_fd,
    const char *relative_path,
    int *parent_fd,
    char leaf_name[NAME_MAX + 1U])
{
    char path[W3_MAX_RELATIVE_PATH_BYTES + 1U];
    char *cursor;
    int current = -1;

    *parent_fd = -1;
    (void)memcpy(path, relative_path, strlen(relative_path) + 1U);
    current = openat(root_fd, ".", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (current < 0) {
        return -1;
    }
    cursor = path;
    for (;;) {
        char *slash = strchr(cursor, '/');
        if (slash == NULL) {
            size_t length = strlen(cursor);
            if (length == 0U || length > NAME_MAX) {
                (void)close(current);
                return -1;
            }
            (void)memcpy(leaf_name, cursor, length + 1U);
            *parent_fd = current;
            return 0;
        }
        *slash = '\0';
        {
            int child;
            struct stat info;
            if (mkdirat(current, cursor, W3_TARGET_ROOT_MODE) != 0 && errno != EEXIST) {
                (void)close(current);
                return -1;
            }
            child = openat(
                current,
                cursor,
                O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
            if (child < 0 || fchown(
                    child,
                    W3_BOOTSTRAP_TRUSTED_UID,
                    W3_BOOTSTRAP_TRUSTED_GID) != 0 ||
                fchmod(child, W3_TARGET_DIRECTORY_MODE) != 0 || fstat(child, &info) != 0 ||
                !S_ISDIR(info.st_mode) || info.st_uid != W3_BOOTSTRAP_TRUSTED_UID ||
                info.st_gid != W3_BOOTSTRAP_TRUSTED_GID ||
                (info.st_mode & (mode_t)07777) != W3_TARGET_DIRECTORY_MODE ||
                fsync(child) != 0 || fsync(current) != 0) {
                if (child >= 0) {
                    (void)close(child);
                }
                (void)close(current);
                return -1;
            }
            (void)close(current);
            current = child;
        }
        cursor = slash + 1;
    }
}

static int w3_prepare_target_entry(
    int target_root_fd,
    const struct w3_file_entry *entry,
    int *needs_copy)
{
    int parent_fd = -1;
    int fd = -1;
    char name[NAME_MAX + 1U];
    struct stat named;
    struct stat opened;
    struct stat final;
    struct stat named_after;
    uint8_t digest[W3_SHA256_BYTES];
    mode_t actual_mode;
    mode_t transitional_mode = entry->mode & (mode_t)0700;
    int result = -1;

    *needs_copy = 0;
    (void)memset(digest, 0, sizeof(digest));
    if (w3_open_target_parent(target_root_fd, entry->path, &parent_fd, name) != 0) {
        goto done;
    }
    if (fstatat(parent_fd, name, &named, AT_SYMLINK_NOFOLLOW) != 0) {
        if (errno == ENOENT) {
            *needs_copy = 1;
            result = 0;
        }
        goto done;
    }
    actual_mode = named.st_mode & (mode_t)07777;
    if (!S_ISREG(named.st_mode) || named.st_nlink != 1 ||
        named.st_uid != W3_BOOTSTRAP_TRUSTED_UID ||
        named.st_gid != W3_BOOTSTRAP_TRUSTED_GID || named.st_size < 0 ||
        (uint64_t)named.st_size > entry->size ||
        (actual_mode != entry->mode &&
            (actual_mode != transitional_mode || named.st_size != 0))) {
        goto done;
    }
    fd = openat(parent_fd, name, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0 || fstat(fd, &opened) != 0 || !w3_same_identity(&named, &opened)) {
        goto done;
    }
    if (actual_mode == entry->mode && (uint64_t)opened.st_size == entry->size) {
        if (w3_hash_fd(fd, entry->size, digest) != 0 ||
            memcmp(digest, entry->sha256, W3_SHA256_BYTES) != 0 ||
            fstat(fd, &final) != 0 ||
            fstatat(parent_fd, name, &named_after, AT_SYMLINK_NOFOLLOW) != 0 ||
            !w3_same_identity(&opened, &final) ||
            !w3_same_identity(&opened, &named_after)) {
            goto done;
        }
        result = 0;
        goto done;
    }

    if (fstat(fd, &final) != 0 ||
        fstatat(parent_fd, name, &named_after, AT_SYMLINK_NOFOLLOW) != 0 ||
        !w3_same_identity(&opened, &final) || !w3_same_identity(&opened, &named_after) ||
        unlinkat(parent_fd, name, 0) != 0 || fsync(parent_fd) != 0 ||
        fstatat(parent_fd, name, &named_after, AT_SYMLINK_NOFOLLOW) == 0 ||
        errno != ENOENT) {
        goto done;
    }
    *needs_copy = 1;
    result = 0;
done:
    (void)memset(digest, 0, sizeof(digest));
    if (fd >= 0) {
        (void)close(fd);
    }
    if (parent_fd >= 0) {
        (void)close(parent_fd);
    }
    return result;
}

static int w3_write_all(int fd, const uint8_t *bytes, size_t length)
{
    size_t offset = 0U;
    while (offset < length) {
        ssize_t count = write(fd, bytes + offset, length - offset);
        if (count < 0 && errno == EINTR) {
            continue;
        }
        if (count <= 0 || (size_t)count > length - offset) {
            return -1;
        }
        offset += (size_t)count;
    }
    return 0;
}

static int w3_copy_entry(
    int source_root_fd,
    int target_root_fd,
    const struct w3_file_entry *entry)
{
    struct w3_leaf source;
    int target_parent = -1;
    int target_fd = -1;
    char target_name[NAME_MAX + 1U];
    uint8_t buffer[W3_COPY_BUFFER_BYTES];
    uint8_t digest[W3_SHA256_BYTES];
    CC_SHA256_CTX hash;
    uint64_t offset = 0U;
    struct stat target_info;
    struct stat target_named;
    int result = -1;

    source.fd = -1;
    source.parent_fd = -1;
    (void)memset(digest, 0, sizeof(digest));
    if (w3_open_relative_source_leaf(source_root_fd, entry, &source) != 0 ||
        w3_open_target_parent(
            target_root_fd,
            entry->path,
            &target_parent,
            target_name) != 0) {
        goto done;
    }
    target_fd = openat(
        target_parent,
        target_name,
        O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC,
        entry->mode);
    if (target_fd < 0 || fchown(
            target_fd,
            W3_BOOTSTRAP_TRUSTED_UID,
            W3_BOOTSTRAP_TRUSTED_GID) != 0 ||
        fchmod(target_fd, entry->mode) != 0 || CC_SHA256_Init(&hash) != 1) {
        goto done;
    }
    while (offset < entry->size) {
        size_t wanted = sizeof(buffer);
        ssize_t count;
        if ((uint64_t)wanted > entry->size - offset) {
            wanted = (size_t)(entry->size - offset);
        }
        count = pread(source.fd, buffer, wanted, (off_t)offset);
        if (count < 0 && errno == EINTR) {
            continue;
        }
        if (count <= 0 || (size_t)count > wanted ||
            CC_SHA256_Update(&hash, buffer, (CC_LONG)count) != 1 ||
            w3_write_all(target_fd, buffer, (size_t)count) != 0) {
            goto done;
        }
        offset += (uint64_t)count;
        if (W3_BOOTSTRAP_FAULT(W3_FAULT_MID_LEAF) != 0) {
            goto done;
        }
    }
    if (pread(source.fd, buffer, 1U, (off_t)offset) != 0 ||
        CC_SHA256_Final(digest, &hash) != 1 ||
        memcmp(digest, entry->sha256, W3_SHA256_BYTES) != 0 ||
        w3_postcheck_leaf(&source) != 0 || fsync(target_fd) != 0 ||
        fstat(target_fd, &target_info) != 0 ||
        fstatat(target_parent, target_name, &target_named, AT_SYMLINK_NOFOLLOW) != 0 ||
        !S_ISREG(target_info.st_mode) || target_info.st_nlink != 1 ||
        target_info.st_uid != W3_BOOTSTRAP_TRUSTED_UID ||
        target_info.st_gid != W3_BOOTSTRAP_TRUSTED_GID ||
        (target_info.st_mode & (mode_t)07777) != entry->mode ||
        target_info.st_size < 0 || (uint64_t)target_info.st_size != entry->size ||
        !w3_same_identity(&target_info, &target_named) || fsync(target_parent) != 0) {
        goto done;
    }
    result = 0;
done:
    (void)memset(buffer, 0, sizeof(buffer));
    (void)memset(digest, 0, sizeof(digest));
    if (target_fd >= 0) {
        (void)close(target_fd);
    }
    if (target_parent >= 0) {
        (void)close(target_parent);
    }
    w3_close_leaf(&source);
    return result;
}

static int w3_read_descriptor(
    const uint8_t supplied_digest[W3_SHA256_BYTES],
    struct w3_descriptor *descriptor)
{
    struct w3_leaf leaf;
    uint8_t measured_digest[W3_SHA256_BYTES];
    char *payload = NULL;
    uint64_t size;
    int result = -1;

    leaf.fd = -1;
    leaf.parent_fd = -1;
    if (w3_open_trusted_leaf(
            W3_BOOTSTRAP_DESCRIPTOR,
            W3_BOOTSTRAP_TRUSTED_UID,
            W3_BOOTSTRAP_TRUSTED_GID,
            W3_DESCRIPTOR_MODE,
            &leaf) != 0 ||
        leaf.initial.st_size <= 0 ||
        (uint64_t)leaf.initial.st_size > W3_DESCRIPTOR_MAX_BYTES) {
        goto done;
    }
    size = (uint64_t)leaf.initial.st_size;
    payload = malloc((size_t)size + 1U);
    if (payload == NULL || w3_hash_fd(leaf.fd, size, measured_digest) != 0 ||
        memcmp(measured_digest, supplied_digest, W3_SHA256_BYTES) != 0 ||
        pread(leaf.fd, payload, (size_t)size, 0) != (ssize_t)size ||
        w3_postcheck_leaf(&leaf) != 0) {
        goto done;
    }
    payload[size] = '\0';
    if (w3_parse_descriptor(payload, (size_t)size, descriptor) != 0) {
        goto done;
    }
    result = 0;
done:
    if (payload != NULL) {
        (void)memset(payload, 0, (size_t)(leaf.initial.st_size > 0 ? leaf.initial.st_size : 0));
        free(payload);
    }
    (void)memset(measured_digest, 0, sizeof(measured_digest));
    w3_close_leaf(&leaf);
    return result;
}

static int w3_verify_self(const struct w3_descriptor *descriptor)
{
    char executable_path[PATH_MAX + 1U];
    uint32_t executable_size = (uint32_t)sizeof(executable_path);
    struct w3_leaf leaf;
    uint8_t digest[W3_SHA256_BYTES];
    int result = -1;

    leaf.fd = -1;
    leaf.parent_fd = -1;
    if (W3_BOOTSTRAP_GET_EXECUTABLE_PATH(executable_path, &executable_size) != 0 ||
        executable_size == 0U || executable_size > sizeof(executable_path) ||
        strcmp(executable_path, W3_BOOTSTRAP_TARGET) != 0 ||
        w3_open_trusted_leaf(
            W3_BOOTSTRAP_TARGET,
            W3_BOOTSTRAP_TRUSTED_UID,
            W3_BOOTSTRAP_TRUSTED_GID,
            W3_BOOTSTRAP_MODE,
            &leaf) != 0 ||
        leaf.initial.st_size <= 0 ||
        w3_hash_fd(leaf.fd, (uint64_t)leaf.initial.st_size, digest) != 0 ||
        memcmp(digest, descriptor->bootstrap_sha256, W3_SHA256_BYTES) != 0 ||
        w3_postcheck_leaf(&leaf) != 0) {
        goto done;
    }
    result = 0;
done:
    (void)memset(executable_path, 0, sizeof(executable_path));
    (void)memset(digest, 0, sizeof(digest));
    w3_close_leaf(&leaf);
    return result;
}

static void w3_encode_prefixed_digest(
    const uint8_t digest[W3_SHA256_BYTES],
    char output[7U + W3_SHA256_HEX_BYTES + 1U])
{
    (void)memcpy(output, "sha256:", 7U);
    w3_encode_digest_hex(digest, output + 7U);
}

static int w3_validate_fixed_entrypoints(const struct w3_descriptor *descriptor)
{
    ssize_t python_index = w3_find_entry(descriptor, W3_BOOTSTRAP_PYTHON_RELATIVE);
    ssize_t executor_index = w3_find_entry(descriptor, W3_BOOTSTRAP_EXECUTOR_RELATIVE);
    return python_index >= 0 && executor_index >= 0 &&
        descriptor->files[(size_t)python_index].mode == (mode_t)0555 &&
        descriptor->files[(size_t)executor_index].mode == (mode_t)0444
        ? 0
        : -1;
}

#ifdef W3_BOOTSTRAP_TESTING
int w3_bootstrap_testing_validate_descriptor_bytes(
    const uint8_t *payload,
    size_t payload_size)
{
    struct w3_descriptor descriptor;
    char *mutable_payload = NULL;
    int result = -1;

    (void)memset(&descriptor, 0, sizeof(descriptor));
    if (payload == NULL || payload_size == 0U ||
        payload_size > W3_DESCRIPTOR_MAX_BYTES) {
        return -1;
    }
    mutable_payload = malloc(payload_size);
    if (mutable_payload == NULL) {
        return -1;
    }
    (void)memcpy(mutable_payload, payload, payload_size);
    if (w3_parse_descriptor(mutable_payload, payload_size, &descriptor) == 0 &&
        w3_validate_fixed_entrypoints(&descriptor) == 0) {
        result = 0;
    }
    (void)memset(mutable_payload, 0, payload_size);
    free(mutable_payload);
    w3_free_descriptor(&descriptor);
    return result;
}
#endif

static int w3_publish_candidate(struct w3_root *candidate)
{
    int parent_fd = -1;
    char target_name[NAME_MAX + 1U];
    struct stat candidate_parent;
    struct stat verified_parent;
    struct stat named;
    size_t target_length;

    if (w3_postcheck_target_root(candidate) != 0 ||
        w3_open_trusted_parent(
            W3_BOOTSTRAP_TARGET_ROOT,
            &parent_fd,
            target_name) != 0 ||
        fstat(candidate->parent_fd, &candidate_parent) != 0 ||
        fstat(parent_fd, &verified_parent) != 0 ||
        candidate_parent.st_dev != verified_parent.st_dev ||
        candidate_parent.st_ino != verified_parent.st_ino ||
        fstatat(parent_fd, target_name, &named, AT_SYMLINK_NOFOLLOW) == 0 ||
        errno != ENOENT ||
        renameatx_np(
            candidate->parent_fd,
            candidate->name,
            parent_fd,
            target_name,
            RENAME_EXCL) != 0 ||
        fsync(parent_fd) != 0) {
        if (parent_fd >= 0) {
            (void)close(parent_fd);
        }
        return -1;
    }
    target_length = strlen(target_name);
    if (target_length > NAME_MAX) {
        (void)close(parent_fd);
        return -1;
    }
    (void)memcpy(candidate->name, target_name, target_length + 1U);
    (void)close(candidate->parent_fd);
    candidate->parent_fd = parent_fd;
    return w3_postcheck_target_root(candidate);
}

static int w3_copy_closed_tree(
    const struct w3_descriptor *descriptor,
    const uint8_t descriptor_digest[W3_SHA256_BYTES],
    struct w3_root *source,
    struct w3_root *target)
{
    size_t index;
    int fixed_state;
    int candidate_created;
    int candidate_complete;
    int expected_candidate_exists;

    if (w3_census_candidate_namespace(
            descriptor_digest,
            &expected_candidate_exists) != 0) {
        return -1;
    }
    fixed_state = w3_open_fixed_target_root(target);
    if (fixed_state == 0) {
        return !expected_candidate_exists &&
            w3_scan_tree(target->fd, descriptor, 1, 1) == 0 &&
            w3_postcheck_target_root(target) == 0 &&
            w3_census_candidate_namespace(
                descriptor_digest,
                &expected_candidate_exists) == 0 &&
            !expected_candidate_exists
            ? 0
            : -1;
    }
    if (fixed_state < 0 ||
        w3_open_or_create_candidate_root(
            descriptor_digest,
            target,
            &candidate_created) != 0 ||
        !w3_is_digest_named_candidate(target, descriptor_digest) ||
        w3_census_candidate_namespace(
            descriptor_digest,
            &expected_candidate_exists) != 0 ||
        !expected_candidate_exists ||
        (candidate_created &&
            W3_BOOTSTRAP_FAULT(W3_FAULT_AFTER_CANDIDATE_ROOT) != 0) ||
        w3_scan_resumable_tree(target->fd, descriptor, &candidate_complete) != 0 ||
        w3_postcheck_target_root(target) != 0) {
        return -1;
    }

    if (!candidate_complete) {
        if (w3_open_untrusted_source_root(source) != 0 ||
            w3_scan_tree(source->fd, descriptor, 0, 1) != 0 ||
            w3_postcheck_source_root(source) != 0) {
            return -1;
        }
        for (index = 0U; index < descriptor->file_count; ++index) {
            int needs_copy;
            if (w3_prepare_target_entry(
                    target->fd,
                    &descriptor->files[index],
                    &needs_copy) != 0 ||
                (needs_copy &&
                    w3_copy_entry(
                        source->fd,
                        target->fd,
                        &descriptor->files[index]) != 0)) {
                return -1;
            }
        }
        if (w3_scan_tree(source->fd, descriptor, 0, 1) != 0 ||
            w3_postcheck_source_root(source) != 0) {
            return -1;
        }
    }

    if (w3_scan_tree(target->fd, descriptor, 1, 1) != 0 ||
        w3_postcheck_target_root(target) != 0 || fsync(target->fd) != 0 ||
        fsync(target->parent_fd) != 0 ||
        W3_BOOTSTRAP_FAULT(W3_FAULT_AFTER_PAYLOAD_COMPLETE) != 0 ||
        w3_publish_candidate(target) != 0 ||
        w3_scan_tree(target->fd, descriptor, 1, 1) != 0 ||
        w3_postcheck_target_root(target) != 0 ||
        w3_census_candidate_namespace(
            descriptor_digest,
            &expected_candidate_exists) != 0 ||
        expected_candidate_exists ||
        W3_BOOTSTRAP_FAULT(W3_FAULT_AFTER_PUBLISH) != 0) {
        return -1;
    }
    return 0;
}

int main(int argc, char *argv[])
{
    uint8_t supplied_descriptor_digest[W3_SHA256_BYTES];
    uint8_t supplied_plan_digest[W3_SHA256_BYTES];
    uint8_t supplied_bundle_digest[W3_SHA256_BYTES];
    struct w3_descriptor descriptor;
    struct w3_root source;
    struct w3_root target;
    char plan_digest[7U + W3_SHA256_HEX_BYTES + 1U];
    char bundle_digest[7U + W3_SHA256_HEX_BYTES + 1U];
    char *const child_argv[] = {
        (char *)W3_BOOTSTRAP_PYTHON,
        (char *)"-I",
        (char *)"-B",
        (char *)"-m",
        (char *)W3_BOOTSTRAP_EXECUTOR_MODULE,
        (char *)"--apply",
        (char *)"--plan-digest",
        plan_digest,
        (char *)"--bundle-digest",
        bundle_digest,
        NULL,
    };
    char *const child_environment[] = {
        (char *)"PATH=/usr/bin:/bin:/usr/sbin:/sbin",
        NULL,
    };
    int status = W3_STATUS_CONTRACT;

    (void)memset(&descriptor, 0, sizeof(descriptor));
    (void)memset(&source, 0, sizeof(source));
    (void)memset(&target, 0, sizeof(target));
    source.fd = -1;
    source.parent_fd = -1;
    target.fd = -1;
    target.parent_fd = -1;
    if (argc != 8 || strcmp(argv[0], W3_BOOTSTRAP_TARGET) != 0 ||
        strcmp(argv[1], "--apply") != 0 ||
        strcmp(argv[2], "--descriptor-digest") != 0 ||
        strcmp(argv[4], "--plan-digest") != 0 ||
        strcmp(argv[6], "--bundle-digest") != 0 ||
        w3_prefixed_digest(argv[3], supplied_descriptor_digest) != 0 ||
        w3_prefixed_digest(argv[5], supplied_plan_digest) != 0 ||
        w3_prefixed_digest(argv[7], supplied_bundle_digest) != 0) {
        (void)fprintf(stderr, "W3_BOOTSTRAP_USAGE\n");
        status = W3_STATUS_USAGE;
        goto done;
    }
    if (W3_BOOTSTRAP_GETEUID() != W3_BOOTSTRAP_REQUIRED_EUID) {
        status = w3_fail("ROOT_REQUIRED");
        goto done;
    }
    if (w3_normalize_process_state() != 0) {
        status = w3_fail("PROCESS_STATE_INVALID");
        goto done;
    }
    w3_clear_process_environment();
    if (chdir("/") != 0) {
        status = w3_fail("PROCESS_CONTEXT_INVALID");
        goto done;
    }
    (void)umask((mode_t)0077);
    if (w3_close_fds_from(3) != 0) {
        status = w3_fail("INHERITED_FD_CENSUS_FAILED");
        goto done;
    }
    if (w3_read_descriptor(supplied_descriptor_digest, &descriptor) != 0) {
        status = w3_fail("DESCRIPTOR_INVALID");
        goto done;
    }
    if (memcmp(supplied_plan_digest, descriptor.plan_sha256, W3_SHA256_BYTES) != 0 ||
        memcmp(supplied_bundle_digest, descriptor.manifest_sha256, W3_SHA256_BYTES) !=
            0 ||
        w3_validate_fixed_entrypoints(&descriptor) != 0) {
        status = w3_fail("OPERATOR_CONSENT_MISMATCH");
        goto done;
    }
    if (w3_verify_self(&descriptor) != 0) {
        status = w3_fail("TRUSTED_BOOTSTRAP_MISMATCH");
        goto done;
    }
    if (w3_copy_closed_tree(
            &descriptor,
            supplied_descriptor_digest,
            &source,
            &target) != 0) {
        /* Digest-named candidates are the only resumable native copy state. */
        status = w3_fail("CLOSED_COPY_FAILED");
        goto done;
    }
    w3_encode_prefixed_digest(descriptor.plan_sha256, plan_digest);
    w3_encode_prefixed_digest(descriptor.manifest_sha256, bundle_digest);
    w3_close_root(&source);
    w3_close_root(&target);
    if (w3_close_fds_from(3) != 0) {
        status = w3_fail("FINAL_FD_CENSUS_FAILED");
        goto done;
    }
    (void)W3_BOOTSTRAP_EXECVE(
        W3_BOOTSTRAP_PYTHON,
        child_argv,
        child_environment);
    status = w3_fail("EXEC_FAILED");
done:
    w3_close_root(&source);
    w3_close_root(&target);
    w3_free_descriptor(&descriptor);
    (void)memset(supplied_descriptor_digest, 0, sizeof(supplied_descriptor_digest));
    (void)memset(supplied_plan_digest, 0, sizeof(supplied_plan_digest));
    (void)memset(supplied_bundle_digest, 0, sizeof(supplied_bundle_digest));
    (void)memset(plan_digest, 0, sizeof(plan_digest));
    (void)memset(bundle_digest, 0, sizeof(bundle_digest));
    return status;
}
