.. highlight:: shell

============
Installation
============

Requirements
------------

Since this is an audio playing Discord bot, there are obviously some
non-python requirements.

* `Python 3.6`_ +. This is avaible on Windows easily and it is also avaible
  on Mac via Homebrew. Also most Linux distros now either ship with 3.6
  or have an easy way to get it, like SCL for RedHat based distros.

* A `SiriusXM`_ account with access to online streaming (not just a car
  radio account)

* A Discord server with a `Bot Application`_ set up on it. You will need
  the "Bot Token"

* `ffmpeg`_ for actually decoding and playing the HLS streams from SiriusXM

* As a requirement from the `Python Discord library`_: `libffi`, `libnacl`,
  `python3-dev`

.. _Python 3.6: https://www.python.org/downloads/
.. _SiriusXM: https://www.siriusxm.com
.. _Bot Application: https://discordapp.com/developers/
.. _ffmpeg: https://ffmpeg.org/download.html
.. _Python Discord library: https://discordpy.readthedocs.io/en/rewrite/intro.html#installing


Github
------

`discord-siriusxm` is not avaible on PyPi quite yet and some of its depenencies
are not yet either. As a result installting it is a bit more difficult. This
assumes your Python 3 executable is just `python` if it is not, replace it with
`python3` or whatever it actually is.

.. code-block:: console

    $ git clone git://github.com/AngellusMortis/discord_siriusxm
    $ cd discord_siriusxm
    $ python -m venv            # this line and the next are optional
    $ source venv/bin/activate  # but if you do not do it then you have to
    $ python setup.py install   # <- run this command with sudo
