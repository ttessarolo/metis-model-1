/*
 * Fixed-target launchd socket shim for the W3 broker and anchor services.
 *
 * The same source is compiled twice with immutable W3_SHIM_LISTENER_NAME and
 * W3_SHIM_MODULE_NAME values. A repository-built binary has no authority.
 * Installed variants must live below root-owned immutable ancestry and be
 * content-bound by the L70 bundle. The shim accepts no arguments, paths or
 * environment from a caller: exactly one launchd Unix stream listener becomes
 * FD 3, every higher descriptor is closed, and execve receives a sterile env.
 */

#include <errno.h>
#include <fcntl.h>
#include <launch.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sysexits.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/un.h>
#include <unistd.h>

#ifndef W3_SHIM_LISTENER_NAME
#define W3_SHIM_LISTENER_NAME "UNSET"
#endif

#ifndef W3_SHIM_PYTHON_PATH
#define W3_SHIM_PYTHON_PATH \
    "/Library/Application Support/MetisModel1/runtime/python/bin/python3.13"
#endif

#ifndef W3_SHIM_MODULE_NAME
#define W3_SHIM_MODULE_NAME "UNSET"
#endif

#define W3_SHIM_SOCKET_FD 3

typedef int (*w3_shim_activate_fn)(const char *, int **, size_t *);
typedef int (*w3_shim_execve_fn)(const char *, char *const[], char *const[]);

static char *const w3_shim_argv[] = {
    W3_SHIM_PYTHON_PATH,
    "-I",
    "-B",
    "-m",
    W3_SHIM_MODULE_NAME,
    NULL,
};
static char *const w3_shim_environment[] = {
    "HOME=/var/empty",
    "LANG=C",
    "LC_ALL=C",
    "PATH=/usr/bin:/bin",
    "TZ=UTC",
    NULL,
};

static int w3_shim_configuration_is_frozen(void)
{
    const int broker = strcmp(W3_SHIM_LISTENER_NAME, "BrokerListener") == 0 &&
                       strcmp(W3_SHIM_MODULE_NAME, "runtime.w3_broker_service") == 0;
    const int anchor = strcmp(W3_SHIM_LISTENER_NAME, "AnchorListener") == 0 &&
                       strcmp(W3_SHIM_MODULE_NAME, "runtime.w3_anchor_service") == 0;

    return strcmp(
               W3_SHIM_PYTHON_PATH,
               "/Library/Application Support/MetisModel1/runtime/python/bin/python3.13"
           ) == 0 &&
           (broker || anchor);
}

static int w3_shim_validate_listener(int descriptor)
{
    int socket_type = 0;
    socklen_t length = sizeof(socket_type);
    struct sockaddr_storage address;
    socklen_t address_length = sizeof(address);

    memset(&address, 0, sizeof(address));
    if (descriptor < W3_SHIM_SOCKET_FD ||
        getsockopt(descriptor, SOL_SOCKET, SO_TYPE, &socket_type, &length) != 0 ||
        socket_type != SOCK_STREAM) {
        errno = EPROTOTYPE;
        return -1;
    }
    if (getsockname(descriptor, (struct sockaddr *)&address, &address_length) != 0 ||
        address.ss_family != AF_UNIX) {
        errno = EPROTOTYPE;
        return -1;
    }
    return 0;
}

static int w3_shim_close_from(int first_descriptor)
{
    long maximum = sysconf(_SC_OPEN_MAX);
    int descriptor;

    if (maximum < 0 || maximum > 1048576L) {
        maximum = 65536L;
    }
    for (descriptor = first_descriptor; descriptor < maximum; ++descriptor) {
        if (close(descriptor) != 0 && errno != EBADF) {
            return -1;
        }
    }
    return 0;
}

static int w3_shim_map_exact_fd3(w3_shim_activate_fn activate_fn)
{
    int *descriptors = NULL;
    size_t count = 0U;
    int activation_error;
    size_t index;

    if (activate_fn == NULL) {
        errno = EINVAL;
        return -1;
    }
    activation_error = activate_fn(W3_SHIM_LISTENER_NAME, &descriptors, &count);
    if (activation_error != 0) {
        errno = activation_error;
        return -1;
    }
    if (descriptors == NULL || count != 1U || w3_shim_validate_listener(descriptors[0]) != 0) {
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
    if (descriptors[0] != W3_SHIM_SOCKET_FD) {
        if (dup2(descriptors[0], W3_SHIM_SOCKET_FD) < 0) {
            int saved_errno = errno;

            (void)close(descriptors[0]);
            free(descriptors);
            errno = saved_errno;
            return -1;
        }
        (void)close(descriptors[0]);
    }
    free(descriptors);
    {
        int flags = fcntl(W3_SHIM_SOCKET_FD, F_GETFD);
        if (flags < 0 || fcntl(W3_SHIM_SOCKET_FD, F_SETFD, flags & ~FD_CLOEXEC) != 0) {
            return -1;
        }
    }
    if (w3_shim_close_from(W3_SHIM_SOCKET_FD + 1) != 0) {
        return -1;
    }
    return 0;
}

static int w3_shim_run_with(w3_shim_activate_fn activate_fn, w3_shim_execve_fn execve_fn)
{
    if (!w3_shim_configuration_is_frozen() || execve_fn == NULL) {
        errno = EINVAL;
        return EX_CONFIG;
    }
    if (w3_shim_map_exact_fd3(activate_fn) != 0 || chdir("/") != 0) {
        return EX_UNAVAILABLE;
    }
    (void)umask(0077);
    execve_fn(W3_SHIM_PYTHON_PATH, w3_shim_argv, w3_shim_environment);
    return EX_OSERR;
}

int main(void)
{
    int outcome = w3_shim_run_with(launch_activate_socket, execve);

    if (outcome != EX_OK) {
        fputs("w3 socket activation shim: fail closed\n", stderr);
    }
    return outcome;
}
