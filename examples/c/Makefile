CC       := gcc
CFLAGS   := -std=c11 -Wall -Wextra -O2
SRCDIR   := src
SRCS     := $(SRCDIR)/main.c $(SRCDIR)/vector3.c $(SRCDIR)/shape.c \
            $(SRCDIR)/circle.c $(SRCDIR)/rectangle.c $(SRCDIR)/renderer.c
OBJS     := $(SRCS:.c=.o)
TARGET   := demo
LDFLAGS  := -lm

LIB_SRCS := $(SRCDIR)/vector3.c $(SRCDIR)/shape.c $(SRCDIR)/circle.c \
            $(SRCDIR)/rectangle.c $(SRCDIR)/renderer.c
TESTS    := test_vector3 test_shape test_circle test_rectangle test_renderer
TEST_DIR := tests

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

$(SRCDIR)/%.o: $(SRCDIR)/%.c
	$(CC) $(CFLAGS) -c $< -o $@

test: $(addprefix $(TEST_DIR)/,$(TESTS))
	@failed=0; \
	for t in $(addprefix $(TEST_DIR)/,$(TESTS)); do \
		echo "--- $$t ---"; \
		./$$t || failed=1; \
	done; \
	exit $$failed

$(TEST_DIR)/%: $(TEST_DIR)/%.c $(LIB_SRCS)
	$(CC) $(CFLAGS) -I$(SRCDIR) -o $@ $^ $(LDFLAGS)

clean:
	rm -f $(OBJS) $(TARGET) $(addprefix $(TEST_DIR)/,$(TESTS))

.PHONY: all test clean
