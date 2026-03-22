CXX      := g++
CXXFLAGS := -std=c++17 -Wall -Wextra -O2
SRCDIR   := src
SRCS     := $(SRCDIR)/main.cpp $(SRCDIR)/vector3.cpp $(SRCDIR)/shape.cpp \
            $(SRCDIR)/circle.cpp $(SRCDIR)/rectangle.cpp $(SRCDIR)/renderer.cpp
OBJS     := $(SRCS:.cpp=.o)
TARGET   := demo

LIB_SRCS := $(SRCDIR)/vector3.cpp $(SRCDIR)/shape.cpp $(SRCDIR)/circle.cpp \
            $(SRCDIR)/rectangle.cpp $(SRCDIR)/renderer.cpp
TESTS    := test_vector3 test_shape test_circle test_rectangle test_renderer
TEST_DIR := tests

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CXX) $(CXXFLAGS) -o $@ $^

$(SRCDIR)/%.o: $(SRCDIR)/%.cpp
	$(CXX) $(CXXFLAGS) -c $< -o $@

test: $(addprefix $(TEST_DIR)/,$(TESTS))
	@failed=0; \
	for t in $(addprefix $(TEST_DIR)/,$(TESTS)); do \
		echo "--- $$t ---"; \
		./$$t || failed=1; \
	done; \
	exit $$failed

$(TEST_DIR)/%: $(TEST_DIR)/%.cpp $(LIB_SRCS)
	$(CXX) $(CXXFLAGS) -I$(SRCDIR) -o $@ $^

clean:
	rm -f $(OBJS) $(TARGET) $(addprefix $(TEST_DIR)/,$(TESTS))

.PHONY: all test clean
