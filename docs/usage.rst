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
