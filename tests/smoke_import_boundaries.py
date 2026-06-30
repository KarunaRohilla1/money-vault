from pathlib import Path
import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[1])
)

from db.accounts import ACCOUNT_TYPES


PRODUCTION_ROOTS = [
    Path("app.py"),
    Path("views"),
    Path("components")
]


def iter_python_files():

    for root in PRODUCTION_ROOTS:

        if root.is_file():

            yield root

        else:

            yield from root.rglob("*.py")


def run():

    assert "Salary Account" in ACCOUNT_TYPES

    offenders = []

    for path in iter_python_files():

        text = path.read_text(
            encoding="utf-8"
        )

        if (
            "from database import" in text
            or "import database" in text
        ):

            offenders.append(
                str(path)
            )

    if offenders:

        raise AssertionError(
            "Production code should import db domain modules, "
            f"not database.py: {offenders}"
        )


if __name__ == "__main__":

    run()

    print("import boundary checks passed")
