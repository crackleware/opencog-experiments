/*
gcc find-max-mmaped-region-size.c -o find-max-mmaped-region-size && ./find-max-mmaped-region-size
*/

#include <stdio.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <linux/falloc.h>
#include <sys/mman.h>

int check_mmap_size(int fd, uint64_t size)
{
    uint8_t* patomspace = mmap(NULL, size, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_SHARED, fd, 0);
    int ok = ((void*)patomspace) != MAP_FAILED;
    if (ok) {
        munmap(patomspace, size);
    }
    /* printf("check_mmap_size: %g bytes: %s\n", (double)size, ok ? "ok" : "fail"); */
    return ok;
}

int main(int argc, char** argv)
{
    int fd = open("atomspace", O_CREAT | O_RDWR, S_IRUSR | S_IWUSR | S_IRGRP | S_IROTH);

    uint64_t GB = (uint64_t)(1024*1024*1024);
    uint64_t TB = (uint64_t)(1024*GB);
    uint64_t start_size = 1*GB;
    uint64_t basesize = 0;
    uint64_t size = start_size;

    while (1) {
        if (check_mmap_size(fd, basesize + size)) {
            size *= 2;
        } else {
            size /= 2;
            basesize = basesize + size;
            if (size <= start_size) break;
            size = start_size;
        }
    }

    printf("max_mmap_size: %g bytes (%.3f TB)\n",
        (double)basesize, (double)basesize/TB);

    close(fd);
    return 0;
}

