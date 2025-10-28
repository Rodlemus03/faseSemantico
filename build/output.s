.text
.globl main
main:
j program_start
program_start:
li $t9, 2
li $t9, 3
mul $t0, $t9, $t9
li $t9, 1
addu $t1, $t9, $t0
move $t2, $t1
li $t9, 2
li $t9, 4
mul $t1, $t9, $t9
li $t9, 1
subu $t0, $t1, $t9
move $t3, $t0
program_end:
li $v0, 10
syscall