from setuptools import setup, find_packages

setup(
    name="Discordia",
    packages=find_packages(),
    package_data={
        "Discordia": ["data/*.json"]
    },  # the game data is loaded at runtime, not imported
)
