# 红外图像处理流水线 C 模型 —— 构建脚本
# 默认使用 clang，也可换成 gcc：make CC=gcc

CC      ?= clang
CFLAGS  ?= -O2 -Wall -Wextra -std=c99
TARGET  := c_model.exe
OBJS    := config.o sampling.o gaussian.o clip.o compress.o hist_eq.o color.o output.o main.o

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $(OBJS)

%.o: %.c config.h
	$(CC) $(CFLAGS) -c $<

.PHONY: clean
clean:
	rm -f $(OBJS) $(TARGET)
