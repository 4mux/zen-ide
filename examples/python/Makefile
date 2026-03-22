PYTHON   := python3
SRCDIR   := src
TEST_DIR := tests
TARGET   := $(SRCDIR)/main.py

all: run

run:
	PYTHONPATH=$(SRCDIR) $(PYTHON) $(TARGET)

test:
	PYTHONPATH=$(SRCDIR) $(PYTHON) -m unittest discover -s $(TEST_DIR) -p "test_*.py" -v

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true

.PHONY: all run test clean
