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


Stable release
--------------

To install sxm-player, run this command in your terminal:

.. code-block:: console

    $ pip install sxm-player

This is the preferred method to install sxm-player, as it will always install
the most recent stable release.

If you don't have `pip`_ installed, this `Python installation guide`_ can guide
you through the process.

.. _pip: https://pip.pypa.io
.. _Python installation guide: http://docs.python-guide.org/en/latest/starting/installation/


From sources
------------

The sources for sxm-player can be downloaded from the `Github repo`_.

You can either clone the public repository:

.. code-block:: console

    $ git clone git://github.com/AngellusMortis/sxm-player

Or download the `tarball`_:

.. code-block:: console

    $ curl  -OL https://github.com/AngellusMortis/sxm-player/tarball/master

Once you have a copy of the source, you can install it with:

.. code-block:: console

    $ python setup.py install


.. _Github repo: https://github.com/AngellusMortis/sxm-player
.. _tarball: https://github.com/AngellusMortis/sxm-player/tarball/master
