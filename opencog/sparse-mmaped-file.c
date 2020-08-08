#include <stdio.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <linux/falloc.h>
#include <sys/mman.h>

int main(int argc, char** argv)
{
    int fd = open("atomspace", O_CREAT | O_RDWR, S_IRUSR | S_IWUSR | S_IRGRP | S_IROTH);

    uint64_t max_size = (uint64_t)10*1024*1024*1024*1024;

    uint8_t dummy = 1;
    pwrite(fd, &dummy, sizeof(dummy), max_size-1);

    /* uint64_t patomspace_addr = 0; */
    /* uint64_t patomspace_addr = 0x75a027e2c000; */
    /* uint64_t patomspace_addr = 0x600000000000; */
    uint64_t patomspace_addr = 0x100000000000;
    uint8_t* patomspace = mmap((void*)patomspace_addr, max_size, PROT_READ | PROT_WRITE | PROT_EXEC, MAP_SHARED | MAP_FIXED, fd, 0);
    if ((int)patomspace == -1) { perror("mmap"); return 1; }
    printf("patomspace: %p\n", patomspace);
    printf("patomspace: @ %d GB\n", ((uint64_t)patomspace)/(1<<30));

    uint64_t chunk_size = 10 * 1024*1024;
    uint64_t chunk_off = max_size - chunk_size; 

    memset(patomspace + chunk_off, 123, chunk_size);

    printf("\n* after create, write:\n");
    system("ls -lh atomspace; du -sh atomspace");

    fallocate(fd, FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE, chunk_off, chunk_size);

    printf("\n* after hole punching (block deallocation):\n");
    system("ls -lh atomspace; du -sh atomspace");

    munmap(patomspace, max_size);
    close(fd);
    return 0;
}

