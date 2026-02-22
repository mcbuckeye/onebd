#!/bin/bash
# BD Intelligence Platform - Test Runner Script
#
# Usage:
#   ./scripts/run_tests.sh              # Run all tests
#   ./scripts/run_tests.sh unit         # Run unit tests only
#   ./scripts/run_tests.sh integration  # Run integration tests only
#   ./scripts/run_tests.sh fast         # Skip slow tests
#   ./scripts/run_tests.sh coverage     # Run with coverage report
#   ./scripts/run_tests.sh smoke        # Quick smoke test

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Set PYTHONPATH to parent directory where unified_api symlink exists
export PYTHONPATH="${PROJECT_DIR}/..:${PYTHONPATH}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}BD Intelligence Platform - Test Suite${NC}"
echo "========================================"
echo ""

# Default test command
PYTEST_CMD="python -m pytest"
PYTEST_ARGS="-v"

# Parse arguments
case "${1:-all}" in
    unit)
        echo -e "${YELLOW}Running unit tests only...${NC}"
        PYTEST_ARGS="$PYTEST_ARGS -m unit"
        ;;
    integration)
        echo -e "${YELLOW}Running integration tests...${NC}"
        PYTEST_ARGS="$PYTEST_ARGS -m integration"
        ;;
    fast)
        echo -e "${YELLOW}Running fast tests (skipping slow)...${NC}"
        PYTEST_ARGS="$PYTEST_ARGS -m 'not slow'"
        ;;
    coverage)
        echo -e "${YELLOW}Running with coverage report...${NC}"
        PYTEST_ARGS="$PYTEST_ARGS --cov=unified_api --cov-report=html --cov-report=term-missing"
        ;;
    smoke)
        echo -e "${YELLOW}Running smoke tests...${NC}"
        PYTEST_ARGS="$PYTEST_ARGS tests/unit/test_database_connections.py tests/unit/test_data_integrity.py -x --tb=short"
        ;;
    cortellis)
        echo -e "${YELLOW}Running Cortellis tests only...${NC}"
        PYTEST_ARGS="$PYTEST_ARGS -m cortellis"
        ;;
    edgar)
        echo -e "${YELLOW}Running Edgar tests only...${NC}"
        PYTEST_ARGS="$PYTEST_ARGS -m edgar"
        ;;
    neo4j)
        echo -e "${YELLOW}Running Neo4j tests only...${NC}"
        PYTEST_ARGS="$PYTEST_ARGS -m neo4j"
        ;;
    parallel)
        echo -e "${YELLOW}Running tests in parallel...${NC}"
        PYTEST_ARGS="$PYTEST_ARGS -n auto"
        ;;
    all)
        echo -e "${YELLOW}Running all tests...${NC}"
        ;;
    *)
        # Assume it's a specific test file or pattern
        echo -e "${YELLOW}Running: $1${NC}"
        PYTEST_ARGS="$PYTEST_ARGS $1"
        ;;
esac

# Check for required environment
if [ ! -f ".env.unified" ] && [ ! -f ".env" ]; then
    echo -e "${YELLOW}Warning: No .env file found. Using default test configuration.${NC}"
fi

# Run tests
echo ""
echo "Command: $PYTEST_CMD $PYTEST_ARGS"
echo ""

$PYTEST_CMD $PYTEST_ARGS

# Report results
EXIT_CODE=$?
echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
else
    echo -e "${RED}Some tests failed. Exit code: $EXIT_CODE${NC}"
fi

exit $EXIT_CODE
