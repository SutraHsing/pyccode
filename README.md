# pyccode

An AI Agent implemented in Python that provides interactive AI assistance with bash tool integration.

## Overview

pyccode is an AI Agent framework that combines the power of AI language models with system-level tool execution. The agent can read files, execute bash commands, write files, and manage complex subtasks through a subagent system.

## Features

- **AI-Powered Code Assistance**: Interactive AI agent that can understand and help with code-related tasks
- **Bash Tool Integration**: Execute system commands, file operations, and other bash utilities
- **Subagent System**: Spawn isolated agents for complex subtasks to maintain clean context
- **Environment Configuration**: Support for custom API endpoints and model selection
- **Interactive Shell**: Command-line interface for direct interaction with the AI agent

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd pyccode

# Install dependencies
pip install -r requirements.txt
# or using uv
uv sync
```

## Quick Start

```bash
# Run the interactive shell
python pyccode.py

# Or execute a specific task
python pyccode.py "explore src/ and summarize the architecture"
```

## Configuration

The agent uses environment variables for configuration:

```bash
# .env file example
ANTHROPIC_BASE_URL=https://your-api-endpoint.com/api/anthropic
ANTHROPIC_API_KEY=your-api-key-here
MODEL_NAME=your-preferred-model
```

## Usage Examples

### File Operations
```bash
python pyccode.py "find all Python files in this directory"
python pyccode.py "read the contents of src/main.py"
python pyccode.py "search for functions in this project"
```

### Code Analysis
```bash
python pyccode.py "summarize the architecture of this project"
python pyccode.py "analyze the dependencies in requirements.txt"
python pyccode.py "find unused imports in the codebase"
```

### Development Tasks
```bash
python pyccode.py "create a new module with the following structure..."
python pyccode.py "refactor this function to improve performance"
python pyccode.py "add tests for the authentication module"
```

## Project Structure

```
pyccode/
├── pyccode.py              # Main AI agent implementation
├── pyproject.toml          # Project configuration
├── .env                    # Environment variables
├── .gitignore              # Git ignore patterns
└── README.md               # This file
```

## Dependencies

- `anthropic>=0.75.0` - AI language model integration
- `dotenv>=0.9.9` - Environment variable management

## Development

### Running Tests
```bash
# Tests are not included in the current version
# Add your test setup here
```

### Contributing
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is licensed under the MIT License. See the LICENSE file for details.

## Support

For issues and questions, please open an issue on GitHub or contact the maintainers.

## Future Development

- [ ] Add support for additional tool integrations
- [ ] Implement persistent memory and context management
- [ ] Add plugin system for extending agent capabilities
- [ ] Improve error handling and user feedback
- [ ] Add web interface alongside CLI

## Authors

- [Your Name] - Initial implementation

---

**Note**: This project implements the essentials of an AI Agent with focus on code assistance and system tool integration. The current implementation provides a solid foundation for building more sophisticated AI-powered development tools.
