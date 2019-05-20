=====
Usage
=====

.. warning:: Designed for PERSONAL USE ONLY

    `sxm-player` is a 100% unofficial project and you use it at your own risk.
    It is designed to be used for personal use with a small number of users
    listening to it at once. Similar to playing music over a speak from the
    radio directly. Using `sxm-player` in any corporate setting, to
    attempt to priate music, or to try to make a profit off your subscription
    may result in you getting in legal trouble.


Command Line Interface
======================

Help
----

Everything is outlined via command line via the `--help` option:

.. code-block:: console

    $ sxm-player --help

Basic Options
-------------

Here are some options that are required no matter what player you choose.
Without declaring a `player_class` argument, `sxm-player` will just run as
HLS proxy. Similar to how the underlaying `sxm` proxy will work. The only
real difference is this is one a lot more reliance to network interuptions
or SXM playback errors.

SXM Parameters
++++++++++++++

Minimally, you must provide your SXM username and password. These are always
required.

.. code-block:: console

    $ sxm-player --username user@example.com --password not_a_real_password

You can also choose to set some extra option SXM related options:

.. code-block:: console

    $ # port to run the SXM proxy server on, defaults to 9999
    $ sxm-player --port 8000

    $ # IP to bind the SXM proxy server to, defaults to 127.0.0.1
    $ sxm-player --host 0.0.0.0

    $ # Manually your SXM region, defaults to US
    $ sxm-player --region CA

Archiving and Processing
++++++++++++++++++++++++

`sxm-player` has support to automatically archive `mp3` files of HLS streams it
plays and splice them into seperate song and show files. It also keeps them
cataloged in a SQLite database so you can query what songs it has stored for
playback.

.. code-block:: console

    $ sxm-player --output-folder /path/to/output

This will create the following directory structure in the output folder::

    archive
        <channel_id>
            <channel_id>.<start_time>.<end_time>.mp3
    processed
        <channel_id>
            shows
                ... organized mp3 files for shows here
            songs
                ... organized mp3 files for songs here
        songs.db
    streams
        <channel_id>.mp3

You should never touch any of these files while the bot is running. Especially
the `mp3` files in the `streams` folder.

`mp3` files for songs/shows are not currently tagged with any metadata because
they are not a perfect fit for when the song/show starts. As a result, I do not
recommend trying to use the `mp3` files that get generated in any other type of
music player. If anyone wants to help get them to be a better fit, help would
be appreicated!

Config File
+++++++++++

`sxm-player` can log any setting from a `yml` style config file. The key for
any setting is the same as the long version of the option with `-` replaced
with `_`.

.. code-block:: yaml

    username: "user@example.com"
    password: "not_a_real_password"
    port: 8000
    host: "0.0.0.0"
    region: "CA"
    output_folder: "/path/to/output"

.. code-block:: console

    $ sxm-player -c /path/to/config

Player Classes
--------------

`sxm-player` offers a pluggable way to create players to run on top of it. To
use a player class, just add it to the end of the `sxm-player` command as an
argument.

.. code-block:: console

    $ sxm-player PlayerClass

Here are a list of know pluggable player classes you can use to extend
`sxm-player`

* `sxm-discord`_: A Discord bot that lets you play SXM content

If you have developed your own player class, make a PR to add it here! Or
make an issue for me to add it.

.. _sxm-discord: https://github.com/AngellusMortis/sxm-discord

CLIPlayer
+++++++++

Out of the box, `sxm-player` only provides one player class. `CLIPlayer`. This
player just plays a given SXM channel to a `mp3` file on disk locally.

.. code-block:: console

    $ sxm-player CLIPlayer --channel-id octane --filename octane.mp3
