import PyInstaller.__main__


def build_exe():
    PyInstaller.__main__.run(
        [
            "app.py",
            "--onefile",
            "--clean",
            "--hidden-import",
            "flask",
            "--hidden-import",
            "python-dotenv",
            "--name",
            "text_adventure_engine",
            "--add-data",
            "templates:templates",
            "--add-data",
            "static:static",
        ]
    )


if __name__ == "__main__":
    build_exe()
