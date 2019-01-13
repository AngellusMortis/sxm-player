=====
Usage
=====

Command Line Interface
======================

Help
----

Everything is outlined via command line via the `--help` option:

.. code-block:: console

    $ dsxm --help

Basic Bot
---------

Command to just run the bot with live SiriusXM radio and not archiving or
archived song/show playback.

.. code-block:: console

    $ dsxm --username sxm_username --password sxm_password --token discord_bot_token

SiriusXM Username, SiriusXM password and Discord Bot token arguments are
optional, if you leave one off, you will be prompted:

.. code-block:: console

    $ dsxm --username sxm_username

Username, password, and Discord Bot token can also be passed via the
`SXM_USERNAME`, `SXM_PASSWORD`, and `DISCORD_TOKEN` environment variables.

.. code-block:: console

    $ export SXM_USERNAME='sxm_username'
    $ export SXM_PASSWORD='sxm_password'
    $ export DISCORD_TOKEN='discord_bot_token'
    $ dsxm

If you are a SiriusXM subscriber in Canada, you will need to change your
region to `CA`

.. code-block:: console

    $ dsxm -r CA

By default, all of the bot commands are prefixed with `/sxm `, if you would
like that to be something different, you can. This will set the command prefix
to `$`.

.. code-block:: console

    $ dsxm --prefix $


Bot + Archiving/Archive Playback
--------------------------------

This will run the bot, but also arhive the HLS live streams as they are played
and splice files out for the songs/shows that have been played.

.. code-block:: console

    $ dsxm -o /path/to/arhive/folder

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


Discord Commands
================

This assumes you have not changed the bot prefix with the `--prefix` option.
Otherwise your bot commands will be a little different.

Help
----

All of the commands can be PM to a user with detailed information:

.. code-block:: console

    $ /sxm help

Utility
-------

Call the bot to the current voice channel. This will move the bot without
stopping the tunes.

.. code-block:: console

    $ /sxm summon

Change volumes. Numbers range from 0% to 100%, bot always starts at 25%.
No argument retrieves volume level.

.. code-block:: console

    $ /sxm volume       # gets current volume level
    $ /sxm volume 100   # sets volume to 100%
    $ /sxm volume 25  $ sets volume to default of 25%

Stops all music playback and kicks bot of out voice channel.

.. code-block:: console

    $ /sxm stop

Resets the bot if it gets stuck in a voice channel. If playing music,
also stops.

.. code-block:: console

    $ /sxm reset

Retrieves what the bot is currently playing.

.. code-block:: console

    $ /sxm playing

Prints a list of the most recent songs played. Defaults to top 3, can display up to 10.

.. code-block:: console

    $ /sxm recent       # displays top 3 songs/shows
    $ /sxm recent 1     # displaying the most recent song/show

SiriusXM Commands
-----------------

PMs the user a full list of all avaiable SiriusXM channels

.. code-block:: console

    $ /sxm channels

Starts playing a SiriusXM channel. `<channel_id>` can be the channel ID,
the channel name or the station number that you see in your car or on the
Web player.

.. code-block:: console

    $ /sxm channel <channel_id>
    $ /sxm channel octane       # will play #37 Octane
    $ /sxm channel 37           # will play #37 Octane

Archive Playback Commands
-------------------------

All of these commands require archiving to be enabled (`-o` argument from
command line).

Search archive for avaible songs. `<search>` string matches again song title or
artist name. Returns only the 10 most recent matches.

.. code-block:: console

    $ /sxm songs <search>

Search archive for avaible shows. `<search>` string matches again title of
episode or the title of the show. Returns only the 10 most recent matches.

.. code-block:: console

    $ /sxm shows <search>

Adds a song to the now playing play queue. `<guid>` must be the one returned
from `songs` command.

.. code-block:: console

    $ /sxm song <guid>

Adds a show to the now playing play queue. `<guid>` must be the one returned
from `shows` command.

.. code-block:: console

    $ /sxm show <guid>

Skips the current playing song/show. If it is the last one, it will
effectivly calling the `stop` command.

.. code-block:: console

    $ /sxm skip

Display all of the songs/shows in the now playing queue

.. code-block:: console

    $ /sxm upcoming

Creates a random infinite playlist of archived songs from a list of channels.
`<channel_id>` is a comma delimited list of channel IDs or the station number.
By default, there must be at least 40 unique songs for that station for the
bot to consider it. You can add an optional arg to override that limit.

.. code-block:: console

    $ /sxm playlist <channel_ids> [threshold]
    $ /sxm playlist octane      # threshold=40, playlist from #37 Octane
    $ /sxm playlist 37,41       # threshold=40, playlist from #37 and #41
    $ /sxm playlist 37 20       # threshold=20, playlist from #37 Octane
