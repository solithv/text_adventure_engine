import PyInstaller.__main__


def build_exe():
    PyInstaller.__main__.run(
        [
            "app.py",
            "--onefile",
            "--add-data",
            "templates:templates",
            "--add-data",
            "static:static",
            "--add-data",
            ".env:.env",
            "--hidden-import",
            "flask",
            "--hidden-import",
            "python-dotenv",
            "--name",
            "text_adventure_engine",
        ]
    )


if __name__ == "__main__":
    build_exe()
