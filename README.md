# Gibby

[![pypi](https://img.shields.io/pypi/v/gibby.svg)](https://pypi.org/project/gibby/)

Gibby - create and manage git backups

```shell
pip install gibby[all]
```

## Basic Usage

```shell
gibby backup 'C:/Users/user/repos' 'Z:/Backups'
gibby restore 'Z:/Backups' 'C:/Users/user/repos'
```

## Use-Case

What's the difference between backing up with `gibby` vs `git push`?

1. Git requires you to organise your code into meaningful commits before being able to push them. Gibby's approach is **just back-up my work, no questions asked**. Thus, by default, Gibby also saves unstaged changes in your working directory.
2. Gibby can be configured to save files ignored by `.gitignore`, such as build results and private keys (try: `gibby snapshot help`). You wouldn't want to commit those to git, but they're useful to have as a hot backup (read about [disaster recovery](https://en.wikipedia.org/wiki/Disaster_recovery)).

## External Dependencies

A non-ancient version of [git](https://git-scm.com/) (I'm testing gibby with version `2.39.2.windows.1`)
