==========
sxm-player
==========

.. image:: https://readthedocs.org/projects/sxm-player/badge/?version=latest
        :target: https://sxm-player.readthedocs.io/en/latest/?badge=latest
        :alt: Documentation Status


.. warning:: Designed for PERSONAL USE ONLY

    `sxm-player` is a 100% unofficial project and you use it at your own risk.
    It is designed to be used for personal use with a small number of users
    listening to it at once. Similar to playing music over a speak from the
    radio directly. Using `sxm-player` in any corporate setting, to
    attempt to priate music, or to try to make a profit off your subscription
    may result in you getting in legal trouble.

A pluggable SXM music player written in Python


* Free software: MIT license
* Documentation: https://sxm-player.readthedocs.io.


Features
--------

* Provides a CLI SXM client
* Can easily provide any SXM client via an anonymous HLS stream that can
  be play on any comptaible remote client
* Provides CLI interface to play SXM channel to a MP3 file on disk
* Can archive live streams from a channel and process any songs/shows from it
* Pluggable API to allow you to create your own SXM clients on top of it

Player Classes
--------------

Here are a list of know pluggable player classes you can use to extend
`sxm-player`

* `sxm-discord`_: A Discord bot that lets you play SXM content

If you have developed your own player class, make a PR to add it here! Or
make an issue for me to add it.

.. _sxm-discord: https://github.com/AngellusMortis/sxm-discord

Credits
-------

This package was created with Cookiecutter_ and the `audreyr/cookiecutter-pypackage`_ project template.

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage
