.option norvc
.section .text
.global _start
.type _start, @function
_start:
    .word 0x5a100013
    addi a0, a0, 1
    addi a0, a0, 2
    .word 0x5a200013
    ret
.size _start, .-_start
