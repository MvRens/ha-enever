# Home Assistant Enever integration

A non-official Home Assistant integration for [Enever.nl](https://enever.nl/) which provides sensors for the gas and electricity price feed data.

There are a few examples of retrieving this data with the built-in RESTful integration. That approach suffers from a few reliability issues however which this integration attempts to solve:

1. When enever.nl is busy or unreachable, the REST sensor will immediately change to Unavailable resulting in missing data in the Energy dashboard.
2. It is tricky to get the current price right. Either the data for "today" needs to be updated at midnight exactly, or a complex template is required to get this data from the "tomorrow" feed in the meantime.
3. The update time for the feeds is not guaranteed, so a check and retry later may be required if you want to get the new prices as soon as possible.


## Provided sensors

TODO

Note: by default all provider-specific sensors are disabled, to prevent clutter. Enable the ones you are interested in on the Entities settings page.


## Installation

### HACS
As I'm personally running Home Assistant in a Docker container, I am not really familiar with HACS. I have followed the guidelines to the best of my knowledge to get this repository ready for HACS, but did not test it. Feel free to open an issue or pull request if changes are required.

### Manual

In the 'custom_components' folder of your Home Assistant installation, create a folder 'enever' and place the files from this repository in that folder. Restart Home Assistant.

The integration should now be available in the Settings.