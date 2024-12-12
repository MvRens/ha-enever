# Home Assistant Enever integration

A non-official Home Assistant integration for [Enever.nl](https://enever.nl/) which provides sensors for the gas and electricity price feed data.

> [!WARNING]
> This integration is still young. This is my first Home Assistant integration, or Python project for that matter, so keep an eye out for those pesky bugs. I am running this in production in my own Home Assistance instance so I hope to spot issues early that way and appreciate any feedback.

There are a few examples of retrieving this data with the built-in RESTful integration. That approach suffers from a few reliability issues however which this integration attempts to solve:

1. When enever.nl is busy or unreachable, the REST sensor will immediately change to Unavailable resulting in missing data in the Energy dashboard.
2. It is tricky to get the current price right. Either the data for "today" needs to be updated at midnight exactly, or a complex template is required to get this data from the "tomorrow" feed in the meantime.
3. The update time for the feeds is not guaranteed, so a check and retry later may be required if you want to get the new prices as soon as possible.

## Table of contents
  * [Provided sensors](#provided-sensors)
    + [Electricity](#electricity)
    + [Gas](#gas)
    + [API request counter](#api-request-counter)
  * [Installation](#installation)
    + [HACS](#hacs)
    + [Manual](#manual)
  * [Configuration](#configuration)
    + [Adding to Home Assistant](#adding-to-home-assistant)
    + [Creating a chart for upcoming prices](#creating-a-chart-for-upcoming-prices)
  * [Developing](#developing)

## Provided sensors

For each supported provider one or two sensors are added for the current electricity price (&euro;/kWh) and/or gas price (&euro;/m&sup3;). These can be used directly as an "entity with current price" in the Energy Dashboard.

These entities are only enabled by default if specified during setup, so you can easily only enable the provider(s) you are interested in. See the Installation section for a screenshot.

### Electricity

The electricity price is fetched from two feeds: today and tomorrow. The entity will update every hour based on the price for the current hour and day based on these two feeds.

The feeds will only be fetched when required, and after the time the feed is supposed to be refreshed, to minimize API token use. This uses up at least two requests per day, but in case a feed is not yet updated it will try again in 15 minutes. As the data for tomorrow should already be known at that time, unless there is an error for more than 24 hours the electricity price should always be available.

Electricity entities also provide the raw data as two attributes, "Today" and "Tomorrow". These contain a list where each entry has a key "datum" containing the date and time, and "prijs" for the price at that time. These attributes will be set to None if the data is not valid for the current date. This means the "Tomorrow" attribute will only be available from around 15:00 - 16:00 to midnight, as it will shift to "Today" by then.

### Gas

The gas price is fetched every day at 6:00 when it should be refreshed. The new price is effective immediately.

If the price feed is not updated it will try again every 15 minutes. The entity will keep the value for the previous day for up to 2 hours, as having a slightly incorrect price is still better than no price for calculating total energy cost.

### API request counter

This sensor keeps track of the amount of API requests performed this month by this integration (not including the one required for validating the token during setup). This is useful to see if the integration is behaving nicely, especially if you are not a supporter and have a limited amount of requests available. If this counter is significantly higher than expected, be sure to open an issue.
Note: this may differ from the actual requests remaining, as all attempts are recorded, including where the API is unreachable.

## Installation

### HACS

As I'm personally running Home Assistant in a Docker container, I am not really familiar with HACS. I have followed the guidelines to the best of my knowledge to get this repository ready for HACS, but did not test it. Feel free to open an issue or pull request if changes are required.

### Manual

In the 'custom_components' folder of your Home Assistant installation, create a folder 'enever' and place the files from this repository in that folder. Restart Home Assistant.

## Configuration
### Adding to Home Assistant

After installation the integration should be available under Settings - Devices & services. Click the Add integration button and search for "Enever".

![Setup](./docs/config_flow.png)

### Creating a chart for upcoming prices

Since the electriciy prices are known in advance you can use the attributes to create a chart. Here is an example using the [ApexCharts card](https://github.com/RomRider/apexcharts-card):

![Chart](./docs/chart.png)

```yaml
type: custom:apexcharts-card
update_interval: 10m
graph_span: 1d
span:
  end: day
now:
  show: true
apex_config:
  grid:
    show: true
  legend:
    show: false
  title:
    text: Stroomprijs vandaag en morgen
    align: center
    floating: true
  tooltip:
    "y":
      formatter: |
        EVAL:function(val) {          
          return val.toFixed(3) + " €/kWh";
        }
yaxis:
  - show: true
    max: ~0.7
    min: 0
    decimals: 1
    apex_config:
      tickAmount: 7
series:
  - entity: sensor.enever_stroomprijs_nextenergy
    type: line
    data_generator: |
      if (!entity.attributes.tomorrow) return [];
      return entity.attributes.tomorrow.map((entry) => {
        const offsetForToday = new Date(entry.datum);
        offsetForToday.setDate(offsetForToday.getDate() - 1);
        
        return [offsetForToday, parseFloat(entry.prijs)];
      });
    color: "#c0c0c0"
  - entity: sensor.enever_stroomprijs_nextenergy
    type: line
    data_generator: |
      if (!entity.attributes.today) return [];
      return entity.attributes.today.map((entry) => {
        return [new Date(entry.datum), parseFloat(entry.prijs)];        
      });
    color: "#03a9f4"
```

## Developing

Follow the instructions for [setting up a development environment](https://developers.home-assistant.io/docs/development_environment). I've chosen VS Code + DevContainers. To get better code checking I have not mounted the code as a custom_component, but instead as a native component by adding the following to the devcontainer.json (change the source path accordingly):

```json
"mounts": [
    "source=${localEnv:HOME}/Projects/ha-enever/custom_components/enever,target=${containerWorkspaceFolder}/homeassistant/components/enever,type=bind"
],
```

There is probably a better way, and the downside is that you need to trick HA into accepting the component.

- Modify `script/hassfest/quality_scale.py` and add `"enever"` to the INTEGRATIONS_WITHOUT_QUALITY_SCALE_FILE array.
- Modify `manifest.json` to pass the schema validation. Remove the `"version"` key and add:
  ```json
  "documentation": "https://www.home-assistant.io/integrations/enever",
  ```
