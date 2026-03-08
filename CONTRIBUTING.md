# Contributing to Beacon

First off, thanks for considering contributing to Beacon. We appreciate you taking the time to make this project better (or at least less broken).

## Code of Conduct

Don't be a jerk. That's it. That's the code of conduct.

(Okay fine, we have a [real one](CODE_OF_CONDUCT.md) too.)

## How Can I Contribute?

### Reporting Bugs

Found a bug? Congrats, you're now a QA engineer. Please open an issue and include:

- What you expected to happen
- What actually happened (bonus points for screenshots of the chaos)
- Steps to reproduce (so we can experience the pain too)
- Your environment (OS, Python version, whether Mercury is in retrograde, etc.)

### Suggesting Features

Have an idea? Great! Open an issue and tell us about it. Just remember: "make it better" is not a feature request.

### Pull Requests

Ready to write some code? Excellent. Here's the deal:

#### Development Setup

```bash
# Clone the repo (you probably already did this)
git clone https://github.com/skyefugate/Beacon.git
cd Beacon

# Set up your Python environment
python3 -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

# Install dependencies
pip install -e ".[dev]"
```

#### The Sacred Development Workflow

1. **Run tests** (because we're professionals here):
   ```bash
   pytest tests/ -m "not integration"
   ```

2. **Format your code** (make it pretty):
   ```bash
   ruff format src/ tests/
   ```

3. **Lint your code** (make it correct):
   ```bash
   ruff check src/ tests/
   ```

4. **Type check** (make it type-safe):
   ```bash
   mypy src/
   ```

Our pre-commit hooks will run formatting and tests automatically, so if you forget these steps, the robots will remind you. Aggressively.

#### Pull Request Guidelines

- **One feature per PR**. Don't be that person who submits "Fixed typo, refactored entire codebase, added blockchain integration."
- **Explain why**. What problem does this solve? Why is this change needed?
- **Write tests**. If you don't, we'll write them for you, and they'll be way more pedantic.
- **Update docs** if you changed behavior. Future you will thank present you.
- **Keep commits atomic**. "Fixed stuff" is not a commit message. Neither is "asdfasdf" (yes, we've seen it).
- **Breaking changes?** Include migration notes so people don't have to reverse-engineer what broke.

#### Licensing

By contributing to Beacon, you agree that your contributions will be licensed under the same MIT License that covers the project. Your code stays open source, you keep your copyright, and everyone can use it under MIT terms.

## Style Guide

- Follow PEP 8 (ruff will yell at you if you don't)
- Use type hints (mypy will yell at you if you don't)
- Write docstrings for public APIs (future developers will yell at you if you don't)
- Keep functions small and focused (your code reviewer will yell at you if you don't)

Basically, avoid getting yelled at.

## Questions?

Open an issue or start a discussion. We're friendly, I promise.

---

Thanks for contributing! You're making network diagnostics slightly less painful for everyone. 🎉
