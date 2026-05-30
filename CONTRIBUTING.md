# Contributing

dap-mux is a small, focused tool. Contributions that help it do its one thing better are welcome.

## Ways to contribute

Not all contributions are code. Bug reports, documentation improvements, and notes on editors or debug adapters you've tested against are all genuinely useful — especially for a project whose compatibility surface is larger than its test suite.

## Start with an issue

Before writing code, open an issue. Describe the problem you're trying to solve or the use case you want to support. Good things happen in issues: the problem gets refined, edge cases surface, and you learn whether the project will accept a solution before you spend time building one.

A pull request with no linked issue gives us nothing to evaluate it against. We can't know if it solves the right problem, if this is the right solution, or if the problem is something this project should solve at all. We'll close it and ask you to open an issue first.

Exception: if you're fixing a clear, unambiguous bug, you can open the PR directly — just describe the behavior you observed and what you changed.

## Scope

dap-mux is a router. It connects debug clients to debug adapters. It is not a platform, and it's not trying to become one.

The right question to ask before proposing a feature: *does this help connect things, or does it add capability that belongs in the client or adapter?* The project will grow, but slowly and deliberately. Proposals that significantly expand scope need to clear a higher bar — start with an issue and make the case.

## What makes a good PR

**It addresses the issue and nothing more.** Small incidental cleanups are fine; sweeping refactors bundled with a feature are not. Focused changes are easier to review, easier to revert, and easier to understand six months later.

**It is good code.** Clear names, no dead code, no commented-out experiments. Code that requires a long explanation to justify is usually code that needs to be changed.

**It comes with tests.** Behavior changes need test coverage. Tests should verify promises — what the code is supposed to do — not implementation details.

**You can defend it.** If AI helped you write the code, that's fine. But you are responsible for it. You should be able to explain every line, debug a failure in it, and adapt it when requirements change. If you can't, the PR can't be proven safe to merge — regardless of how it was written.

## Development setup

You need [uv](https://docs.astral.sh/uv/) and [prek](https://github.com/drmikehenry/prek).

```
git clone https://github.com/dap-mux/dap-mux
cd dap-mux
uv sync --group dev
prek install
```

If you use [direnv](https://direnv.net/), a `.envrc.sample` is committed. Copy or symlink it to `.envrc` and direnv will activate the virtualenv automatically whenever you enter the project directory.

`prek install` sets up the pre-commit hooks. After that, every commit automatically runs secret scanning, linting, formatting, type checking, and the test suite. If any of them fail, the commit doesn't happen.

## Tests and code quality

The pre-commit hooks run everything automatically. To run tools individually:

```
uv run pytest          # test suite
uv run ruff check .    # lint
uv run ruff format .   # format
uv run ty check        # type check
```

All four must pass before a PR is ready to review.

## License

By submitting a pull request, you agree that your contribution will be licensed under the [MIT License](LICENSE.md) that covers this project, and that you have the right to grant that license.
