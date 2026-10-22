# 红外图像处理流水线 C 模型 —— 构建脚本
#
# 默认使用 clang，也可换成 gcc：
#   make                  # clang（Windows 上需在 VS 开发者命令行里，或已装 MinGW 版 clang）
#   make CC=gcc           # gcc / MinGW-w64
#   make clean
#
# 注意：MSVC 的 cl.exe 不吃这些 Unix 风格参数，请直接用 README 里给出的 cl 命令行。

CC      ?= clang
CFLAGS  ?= -O2 -Wall -Wextra -std=c99
LDFLAGS ?=
TARGET  := c_model.exe

# 全部源文件（缺一不可：main.c 依赖 registers.c 里的 g_regs / regs_init /
# capture_raw_do / capture_out_do）
SRCS    := config.c sampling.c gaussian.c clip.c compress.c hist_eq.c \
           color.c output.c registers.c main.c
OBJS    := $(SRCS:.c=.o)

.PHONY: all clean
all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) $(LDFLAGS) -o $@ $(OBJS)

# 所有模块都只依赖自己的源码与统一头文件 config.h
%.o: %.c config.h
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f $(OBJS) $(TARGET)
# Windows cmd 下若无 rm，可改用：del /q *.o c_model.exe
