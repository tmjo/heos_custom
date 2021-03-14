# Custom improvement of the offial HA integration for Denon HEOS

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs) ![Maintenance](https://img.shields.io/maintenance/yes/2021.svg)

The official integration for [Denon HEOS](https://www.home-assistant.io/integrations/heos/) in [Home Assistant](https://www.home-assistant.io/) unfortunately lacks the grouping feature. Work is ongoing to add such features to the official integration, but due to some architectual discussions and the time it takes to conclude those, this custom integration allows HEOS-users to start grouping already today. Once this is implemented in the official integration, this custom integration will probably cease to exist. Follow the progress on official work (by others) [here](https://github.com/home-assistant/architecture/issues/364) and [here](https://github.com/home-assistant/core/pull/32568).

The grouping feature is available as service calls **join** and **unjoin** but for the best user experience I recommend using the amazing [mini-media-card](https://github.com/kalkih/mini-media-player) which has the grouping feature working from UI/Lovelace.


## Installation

There are 2 different methods of installing the custom component. HACS is by far the simplest way for unexperienced users and is recomended.

### HACS installation
The installation is not - and will never be - included in HACS as a default repo. Mainly since it is only meant as a temporary fix for the lack of grouping feature. However, it can be installed through HACS *by adding this repo as a custom repository*. When installed it will override the official integration and a warning for using custom integration should be shown in your Home Assistant log upon startup.

1. Make sure you have [HACS](https://hacs.xyz/) installed in your Home Assistant environment.
2. Go to **HACS**, select **Integrations**.
3. Click on the three dots in the upper right corner and select **Custom repositories**
4. Copy/paste the **URL for this repo** `https://github.com/tmjo/heos_custom` into the URL-field, select **Integration as category** and then click **Add**.
5. You should now find the HEOS Custom integration by searching for it. Install it and restart Home Assistant.


### Git installation

1. Make sure you have git installed on your machine.
2. Navigate to you home assistant configuration folder.
3. Create a `custom_components` folder of it does not exist, navigate down into it after creation.
4. Execute the following command: `git clone https://github.com/tmjo/heos_custom heos_custom`
5. Run `bash links.sh`

## Configuration

Configuration is done through in Configuration > Integrations where you add it with the + icon.
