NODE     := node
SRCDIR   := src
TEST_DIR := tests
TESTS    := $(wildcard $(TEST_DIR)/*.test.js)
TARGET   := $(SRCDIR)/main.js

all: run

run:
	$(NODE) $(TARGET)

test:
	@failed=0; \
	for t in $(TESTS); do \
		echo "--- $$t ---"; \
		$(NODE) --test $$t || failed=1; \
	done; \
	exit $$failed

clean:
	rm -rf node_modules

.PHONY: all run test clean
