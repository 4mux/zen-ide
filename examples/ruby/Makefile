SRCDIR = src

.PHONY: all run test clean

all: run

run:
	ruby -I$(SRCDIR) $(SRCDIR)/main.rb

test:
	@for f in tests/*_test.rb; do \
		echo "=== $$f ==="; \
		ruby -I$(SRCDIR) "$$f"; \
	done

clean:
	@find . -name '*.gem' -delete 2>/dev/null || true
