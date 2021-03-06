# Web

Web for Python Canarias made in Django.

## Python dependencies

### Pipenv

This projects uses [Pipenv](https://pipenv.readthedocs.io/en/latest/).

> Pipenv is a tool that aims to bring the best of all packaging worlds (bundler, composer, npm, cargo, yarn, etc.) to the Python world.

Some of its great features are:

- Enables truly deterministic builds, while easily specifying only what you want.
- Generates and checks file hashes for locked dependencies.
- Automatically install required Pythons, if pyenv is available.
- Automatically finds your project home, recursively, by looking for a Pipfile.
- Automatically generates a Pipfile, if one doesn’t exist.
- Automatically creates a virtualenv in a standard location.
- Automatically adds/removes packages to a Pipfile when they are un/installed.
- Automatically loads .env files, if they exist.

#### Proceed

After you have cloned the repo, make:

~~~console
$ pipenv install --python 3.6
~~~

This will install a virtual environment for the project, with Python 3.6, Django and all the rest Python dependencies.

## Node.js dependencies

It's essential to use `npm >= 6.0.0` and `node >= 10.0.0` in order to update properly the `package-lock.json`.

There are some libraries (*css, js*) used on either the *frontend* or the *development phase*. To install them, make:

~~~console
$ npm install
~~~

> This will create a bunch of folders and files under `node_modules`.

## Other dependencies

One of the Python dependencies is [wkhtmltopdf](https://github.com/JazzCore/python-pdfkit). Besides the proper Python package, you have to install the system package. In our experience with *Ubuntu 18.04 Bionic* you should do the following:

~~~console
$ wget https://downloads.wkhtmltopdf.org/0.12/0.12.5/wkhtmltox_0.12.5-1.bionic_amd64.deb
$ sudo dpkg -i https://downloads.wkhtmltopdf.org/0.12/0.12.5/wkhtmltox_0.12.5-1.bionic_amd64.deb
## in case there are other not resolved dependencies
$ sudo apt-get -f install
~~~

## Developing

### EditorConfig

Please install the corresponding extension of [EditorConfig](https://editorconfig.org/) in your favourite editor. Thus your editor will pick the settings stored in `.editorconfig`.

This configuration avoids conflicts with a lot of settings, mainly with tabs widths.

### Customize your settings

Feel free to change some of the settings creating a file called `.venv` on the root of the project.

### Database

We are using **PostgreSQL** as *database management system*. In order to configure the project correctly it is important to follow some indications:

#### Approach A

1. Install [PostgreSQL](https://www.postgresql.org/download/).
2. Create a *database* and a *user/password* with full access to that database.
3. Set the following keys in the `.env` file: `DATABASE_NAME`, `DATABASE_USER` and `DATABASE_PASSWORD`.

#### Approach B

1. Install [Docker](https://docs.docker.com/install/).
2. Use the following `Dockerfile`:

~~~docker
postgres:
  image: "postgres:10.4"
  environment:
    POSTGRES_DB: "my_db"
  ports:
    - 5432:5432
~~~

Afterwards, in both cases, you can apply migrations with:

~~~console
$ pipenv run python manage.py migrate
~~~

### Launching services

In order to develop, you have to launch the following services:

~~~console
$ pipenv run python manage.py runserver # on one terminal
$ gulp watch                 # on another terminal
~~~

After that, you'll be able to access the project on http://127.0.0.1:8000

The changes made both in Python files or static files will be detected by the services and will reload them.

### Model graphs

~~~console
$ pipenv run python manage.py graph_models events organizations locations speakers tickets schedule -g -S -o models.png
~~~
