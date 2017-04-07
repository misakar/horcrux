#include <sys/types.h>
#include <sys/wait.h>
#include <sys/mount.h>
#include <stdio.h>
#include <sched.h>
#include <signal.h>
#include <unistd.h>

#define STACK_SIZE (1024 * 1024)
static char container_stack[STACK_SIZE];

char * const container_args[] = {
    "/bin/bash", // char * 字符串
    NULL
};

int container_main(void *arg) {
    printf("container [%5d] >> into main container\n", getpid());
    sethostname("neo1218", 8);
    if (mount("proc", "rootfs/proc", "proc", 0, NULL) != 0) {
        perror("proc");
    }
    if (mount("sysfs", "rootfs/sys", "sysfs", 0, NULL) != 0) {
        perror("sys");
    }
    if (mount("none", "rootfs/tmp", "tmpfs", 0, NULL) != 0) {
        perror("tmp");
    }
    if (mount("udev", "rootfs/dev", "devtmpfs", 0, NULL) != 0) {
        perror("dev");
    }
    if (mount("devpts", "rootfs/dev/pts", "devpts", 0, NULL) != 0) {
        perror("dev/pts");
    }
    if (mount("shm", "rootfs/dev/shm", "tmpfs", 0, NULL) != 0) {
        perror("dev/shm");
    }
    if (mount("tmpfs", "rootfs/run", "tmpfs", 0, NULL) != 0) {
        perror("run");
    }
    // 配置文件
    if (mount("conf/hosts", "rootfs/etc/hosts", "none", MS_BIND, NULL) != 0 ||
        mount("conf/hostname", "rootfs/etc/hostname", "none", MS_BIND, NULL) != 0 ||
        mount("conf/resolv.conf", "rootfs/etc/resolv.conf", "none", MS_BIND, NULL) != 0) {
        perror("conf");
    }
    if (chdir("./rootfs") != 0) {
    // if (chroot("./") || chdir("./rootfs") != 0) {
        perror("chdir");
    }
    // chroot 隔离, 将容器进程jail到rootfs中
    if (chroot("./") != 0) {
        perror("chroot");
    }
    // system("mount -t proc proc /proc");
    execv(container_args[0], container_args); // 进入bash
    perror("execv");
    printf("container_main >> something wrong\n");
    return 1;
}

int main(int argc, char **argv) {
    printf("parent [%5d] >> start main container\n", getpid());
    // 创建子进程(不过这里是容器)
    int container_pid = clone(container_main, container_stack+STACK_SIZE, 
            CLONE_NEWUTS | CLONE_NEWIPC | CLONE_NEWPID | CLONE_NEWNS | SIGCHLD, NULL); // UTS NS隔离, 子进程hostname修改不会影响父进程
    waitpid(container_pid, NULL, 0);
    printf("parent >> main container stopped\n");
    return 0;
}
