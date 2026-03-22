RUSTC    := rustc
RFLAGS   := --edition 2021 -O
SRCDIR   := src
LIB      := target/libshapes.rlib
TARGET   := demo

TESTS    := test_vector3 test_shape test_circle test_rectangle test_renderer
TEST_DIR := tests

all: $(TARGET)

$(LIB): $(wildcard $(SRCDIR)/*.rs)
	@mkdir -p target
	$(RUSTC) $(RFLAGS) --crate-type lib --crate-name shapes $(SRCDIR)/lib.rs -o $@

$(TARGET): $(SRCDIR)/main.rs $(LIB)
	$(RUSTC) $(RFLAGS) --extern shapes=$(LIB) $< -o $@

test: $(addprefix $(TEST_DIR)/,$(TESTS))
	@failed=0; \
	for t in $(addprefix $(TEST_DIR)/,$(TESTS)); do \
		echo "--- $$t ---"; \
		./$$t || failed=1; \
	done; \
	exit $$failed

$(TEST_DIR)/%: $(TEST_DIR)/%.rs $(LIB)
	$(RUSTC) $(RFLAGS) --test --extern shapes=$(LIB) $< -o $@

clean:
	rm -rf target $(TARGET) $(addprefix $(TEST_DIR)/,$(TESTS))

.PHONY: all test clean
