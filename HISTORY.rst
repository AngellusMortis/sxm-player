=======
History
=======

0.2.5 (2021-07-30)
------------------

* Fixes log_file option
* Updates requirements

0.2.4 (2021-07-23)
------------------

* Adds args from latest `sxm`
* Improves performance on `PlayerState.get_channel`

0.2.3 (2021-07-17)
------------------

* Adds env var for `CLIPlayer` `channel-id`: `SXM_CLI_CHANNEL_ID`
* Adds env var for `CLIPlayer` `filename`: `SXM_CLI_FILENAME`

0.2.2 (2021-07-17)
------------------

* Adds env var for `player_class`: `SXM_PLAYER_CLASS`

0.2.1 (2021-07-17)
------------------

* Adds missing py.typed to add stubs
* Renames `queue.Event` enum to `queue.EventTypes`

0.2.0 (2021-07-15)
------------------

* Replaces setuptools with filt
* Updates linting
* Replaces TravisCI with Github Actions
* Replaces requests with httpx
* Replaces click with typer
* Adds Pydantic `PlayerState`, `Song` and `Episode` models
* Updates for `sxm==0.2.5` client

0.1.0 (2018-12-25)
------------------

* First release on PyPI.
