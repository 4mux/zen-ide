#ifndef TEST_RUNNER_H
#define TEST_RUNNER_H

#include <stdio.h>
#include <math.h>

static int _tests_passed = 0;
static int _tests_failed = 0;

#define DESCRIBE(name) printf("\n%s\n", name)

#define IT(name, body) do { \
    printf("  %s: ", name); \
    body \
    printf("PASS\n"); \
    _tests_passed++; \
} while (0)

#define EXPECT_EQ(a, b) do { \
    if ((a) != (b)) { \
        printf("FAIL (%s != %s)\n", #a, #b); \
        _tests_failed++; return 1; \
    } \
} while (0)

#define EXPECT_NEAR(a, b, eps) do { \
    if (fabs((a) - (b)) > (eps)) { \
        printf("FAIL (|%s - %s| > %s, got %f vs %f)\n", \
               #a, #b, #eps, (double)(a), (double)(b)); \
        _tests_failed++; return 1; \
    } \
} while (0)

#define EXPECT_TRUE(cond) do { \
    if (!(cond)) { \
        printf("FAIL (%s)\n", #cond); \
        _tests_failed++; return 1; \
    } \
} while (0)

#define EXPECT_STR_EQ(a, b) do { \
    if (strcmp((a), (b)) != 0) { \
        printf("FAIL (\"%s\" != \"%s\")\n", (a), (b)); \
        _tests_failed++; return 1; \
    } \
} while (0)

#define SUMMARY() do { \
    printf("\n%d passed, %d failed\n", _tests_passed, _tests_failed); \
    return _tests_failed > 0 ? 1 : 0; \
} while (0)

#endif
