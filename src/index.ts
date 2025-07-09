import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

import { ISettingRegistry } from '@jupyterlab/settingregistry';

/**
 * Initialization data for the git_lock_sign_jlx extension.
 */
const plugin: JupyterFrontEndPlugin<void> = {
  id: 'git_lock_sign_jlx:plugin',
  description: 'A JupyterLab extension.',
  autoStart: true,
  optional: [ISettingRegistry],
  activate: (app: JupyterFrontEnd, settingRegistry: ISettingRegistry | null) => {
    console.log('JupyterLab extension git_lock_sign_jlx is activated!');

    if (settingRegistry) {
      settingRegistry
        .load(plugin.id)
        .then(settings => {
          console.log('git_lock_sign_jlx settings loaded:', settings.composite);
        })
        .catch(reason => {
          console.error('Failed to load settings for git_lock_sign_jlx.', reason);
        });
    }
  }
};

export default plugin;
