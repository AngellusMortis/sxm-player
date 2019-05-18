.. highlight:: shell

============
Installation
============

Requirements
------------

Since this is an audio playing sxm-player, there are obviously some
non-python requirements.

* `Python 3.6`_ +. This is avaible on Windows easily and it is also avaible
  on Mac via Homebrew. Also most Linux distros now either ship with 3.6
  or have an easy way to get it, like SCL for RedHat based distros.

* A SXM account with access to online streaming (not just a car
  radio account)

* `ffmpeg`_ for actually decoding and playing the HLS streams from SXM

.. _Python 3.6: https://www.python.org/downloads/
.. _ffmpeg: https://ffmpeg.org/download.html


Github
------

`sxm_player` is not avaible on PyPi quite yet and some of its
depenencies are not yet either. As a result installting it is a bit more
difficult. Thisassumes your Python 3 executable is just `python` if it
is not, replace it with `python3` or whatever it actually is.

.. code-block:: console

    $ git clone git://github.com/AngellusMortis/sxm-player
    $ cd sxm_player
    $ python -m venv            # this line and the next are optional
    $ source venv/bin/activate  # but if you do not do it then you have to
    $ python setup.py install   # <- run this command with sudo
