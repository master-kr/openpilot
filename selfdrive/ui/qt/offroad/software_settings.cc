#include "selfdrive/ui/qt/offroad/settings.h"

#include <cassert>
#include <cmath>
#include <string>

#include <QDebug>
#include <QLabel>
#include <QProcess>
#include <QProcessEnvironment>
#include <QTimer>
#include <QVariant>

#include "common/params.h"
#include "common/util.h"
#include "selfdrive/ui/ui.h"
#include "selfdrive/ui/qt/util.h"
#include "selfdrive/ui/qt/widgets/controls.h"
#include "selfdrive/ui/qt/widgets/input.h"
#include "system/hardware/hw.h"


void SoftwarePanel::requestUpdate(bool fetch) {
  // In OfflineMode the manager starts updated only for this explicit request.
  params.putInt("UpdaterUserRequest", fetch ? 2 : 1);
  std::system(fetch ? "pkill -SIGHUP -f system.updated.updated" :
                      "pkill -SIGUSR1 -f system.updated.updated");
}

QStringList SoftwarePanel::availableBranches(const QString &remote_output) {
  QStringList branches;

  auto add_branch = [&branches](QString branch) {
    branch = branch.trimmed();
    if (branch.startsWith("origin/")) branch.remove(0, QString("origin/").size());
    if (!branch.isEmpty() && branch != "HEAD" && !branches.contains(branch)) {
      branches.push_back(branch);
    }
  };

  // A user-initiated remote lookup is the source of truth. The persistent
  // cache keeps the selector useful when the network is temporarily absent.
  for (const QString &line : remote_output.split('\n', QString::SkipEmptyParts)) {
    const QStringList fields = line.simplified().split(' ', QString::SkipEmptyParts);
    if (fields.size() == 2 && fields[1].startsWith("refs/heads/")) {
      add_branch(fields[1].mid(QString("refs/heads/").size()));
    }
  }
  if (remote_output.isEmpty()) {
    for (const QString &branch : QString::fromStdString(params.get("UpdaterAvailableBranches")).split(",", QString::SkipEmptyParts)) {
      add_branch(branch);
    }
  }

  const QString current = QString::fromStdString(params.get("GitBranch"));
  const QString target = QString::fromStdString(params.get("UpdaterTargetBranch"));
  add_branch(current);
  add_branch(target);
  branches.sort(Qt::CaseInsensitive);

  // Keep the installed and selected branches at the top without inventing
  // branch names that do not exist on this repository's remote.
  for (const QString &branch : {target, current}) {
    const int index = branches.indexOf(branch);
    if (index > 0) branches.move(index, 0);
  }
  return branches;
}

void SoftwarePanel::showBranchSelection(QStringList branches) {
  if (branches.isEmpty()) {
    ConfirmationDialog::alert(tr("Unable to load the branch list. Check the network connection."), this);
    return;
  }

  QString current = QString::fromStdString(params.get("UpdaterTargetBranch"));
  if (current.isEmpty()) current = QString::fromStdString(params.get("GitBranch"));
  const QString selection = MultiOptionDialog::getSelection(tr("Select a branch"), branches, current, this);
  if (!selection.isEmpty()) {
    params.put("UpdaterTargetBranch", selection.toStdString());
    targetBranchBtn->setValue(selection);
    requestUpdate(false);
  }
}

void SoftwarePanel::refreshBranches() {
  targetBranchBtn->setEnabled(false);
  targetBranchBtn->setValue(tr("loading branches..."));

  auto process = new QProcess(this);
  QProcessEnvironment environment = QProcessEnvironment::systemEnvironment();
  environment.insert("GIT_TERMINAL_PROMPT", "0");
  process->setProcessEnvironment(environment);
  process->setProcessChannelMode(QProcess::SeparateChannels);

  connect(process, QOverload<int, QProcess::ExitStatus>::of(&QProcess::finished), this,
          [this, process](int exit_code, QProcess::ExitStatus exit_status) {
    if (process->property("branchRefreshHandled").toBool()) return;
    process->setProperty("branchRefreshHandled", true);
    const QString output = QString::fromUtf8(process->readAllStandardOutput());
    const bool remote_success = exit_status == QProcess::NormalExit && exit_code == 0 &&
                                output.contains("refs/heads/");
    const QStringList remote_branches = availableBranches(remote_success ? output : QString());

    if (remote_success) {
      params.put("UpdaterAvailableBranches", remote_branches.join(",").toStdString());
    }

    targetBranchBtn->setEnabled(true);
    updateLabels();
    process->deleteLater();

    // A cache containing only the current branch is the known failure mode
    // caused by a restricted fetch refspec; do not present it as a valid list
    // after a failed remote lookup.
    if (!remote_success && remote_branches.size() <= 1) {
      ConfirmationDialog::alert(tr("Unable to load the branch list. Check the network connection."), this);
      return;
    }
    showBranchSelection(remote_branches);
  });
  connect(process, &QProcess::errorOccurred, this, [this, process](QProcess::ProcessError error) {
    if (error == QProcess::FailedToStart && !process->property("branchRefreshHandled").toBool()) {
      process->setProperty("branchRefreshHandled", true);
      targetBranchBtn->setEnabled(true);
      updateLabels();
      ConfirmationDialog::alert(tr("Unable to load the branch list. Check the network connection."), this);
      process->deleteLater();
    }
  });

  // Avoid leaving the button stuck if DNS or the remote is unavailable.
  QTimer::singleShot(20000, process, [process]() {
    if (process->state() != QProcess::NotRunning) process->kill();
  });
  process->start("git", {"ls-remote", "--heads", "origin"});
}

SoftwarePanel::SoftwarePanel(QWidget* parent) : ListWidget(parent) {
  onroadLbl = new QLabel(tr("Updates are only downloaded while the car is off."));
  onroadLbl->setStyleSheet("font-size: 50px; font-weight: 400; text-align: left; padding-top: 30px; padding-bottom: 30px;");
  addItem(onroadLbl);

  // current version
  versionLbl = new LabelControl(tr("Current Version"), "");
  addItem(versionLbl);

  // download update btn
  downloadBtn = new ButtonControl(tr("Download"), tr("CHECK"));
  connect(downloadBtn, &ButtonControl::clicked, [=]() {
    downloadBtn->setEnabled(false);
    if (downloadBtn->text() == tr("CHECK")) {
      requestUpdate(false);
    } else {
      requestUpdate(true);
    }
  });
  addItem(downloadBtn);

  // install update btn
  installBtn = new ButtonControl(tr("Install Update"), tr("INSTALL"));
  connect(installBtn, &ButtonControl::clicked, [=]() {
    installBtn->setEnabled(false);
    params.putBool("DoReboot", true);
  });
  addItem(installBtn);

  // branch selecting
  targetBranchBtn = new ButtonControl(tr("Target Branch"), tr("SELECT"));
  connect(targetBranchBtn, &ButtonControl::clicked, this, &SoftwarePanel::refreshBranches);
  if (!params.getBool("IsTestedBranch")) {
    addItem(targetBranchBtn);
  }

  // uninstall button
  auto uninstallBtn = new ButtonControl(tr("Uninstall %1").arg(getBrand()), tr("UNINSTALL"));
  connect(uninstallBtn, &ButtonControl::clicked, [&]() {
    if (ConfirmationDialog::confirm(tr("Are you sure you want to uninstall?"), tr("Uninstall"), this)) {
      params.putBool("DoUninstall", true);
    }
  });
  addItem(uninstallBtn);

  fs_watch = new ParamWatcher(this);
  QObject::connect(fs_watch, &ParamWatcher::paramChanged, [=](const QString &param_name, const QString &param_value) {
    updateLabels();
  });

  connect(uiState(), &UIState::offroadTransition, [=](bool offroad) {
    is_onroad = !offroad;
    updateLabels();
  });

  updateLabels();
}

void SoftwarePanel::showEvent(QShowEvent *event) {
  // nice for testing on PC
  installBtn->setEnabled(true);

  updateLabels();
}

void SoftwarePanel::updateLabels() {
  // add these back in case the files got removed
  fs_watch->addParam("LastUpdateTime");
  fs_watch->addParam("UpdateFailedCount");
  fs_watch->addParam("UpdaterState");
  fs_watch->addParam("UpdateAvailable");
  fs_watch->addParam("UpdaterFetchAvailable");
  fs_watch->addParam("UpdaterTargetBranch");
  fs_watch->addParam("UpdaterUserRequest");
  fs_watch->addParam("LastUpdateException");

  if (!isVisible()) {
    return;
  }

  // updater only runs offroad
  onroadLbl->setVisible(is_onroad);
  downloadBtn->setVisible(!is_onroad);

  // download update
  QString updater_state = QString::fromStdString(params.get("UpdaterState"));
  const bool request_pending = params.getInt("UpdaterUserRequest") == 1 || params.getInt("UpdaterUserRequest") == 2;
  bool failed = std::atoi(params.get("UpdateFailedCount").c_str()) > 0;
  if (request_pending && (updater_state.isEmpty() || updater_state == "idle")) {
    downloadBtn->setEnabled(false);
    downloadBtn->setValue(tr("starting updater..."));
  } else if (!updater_state.isEmpty() && updater_state != "idle") {
    downloadBtn->setEnabled(false);
    if (updater_state == "starting updater...") updater_state = tr("starting updater...");
    else if (updater_state == "preparing update...") updater_state = tr("preparing update...");
    else if (updater_state == "checking...") updater_state = tr("checking...");
    else if (updater_state == "downloading...") updater_state = tr("downloading...");
    else if (updater_state == "finalizing update...") updater_state = tr("finalizing update...");
    downloadBtn->setValue(updater_state);
  } else {
    if (failed) {
      downloadBtn->setText(tr("CHECK"));
      QString failure = QString::fromStdString(params.get("LastUpdateException")).section('\n', 0, 0).trimmed();
      downloadBtn->setValue(failure.isEmpty() ? tr("failed to check for update") :
                                             tr("update failed: %1").arg(failure));
    } else if (params.getBool("UpdaterFetchAvailable")) {
      downloadBtn->setText(tr("DOWNLOAD"));
      downloadBtn->setValue(tr("update available"));
    } else {
      QString lastUpdate = tr("never");
      auto tm = params.get("LastUpdateTime");
      if (!tm.empty()) {
        lastUpdate = timeAgo(QDateTime::fromString(QString::fromStdString(tm + "Z"), Qt::ISODate));
      }
      downloadBtn->setText(tr("CHECK"));
      downloadBtn->setValue(tr("up to date, last checked %1").arg(lastUpdate));
    }
    downloadBtn->setEnabled(true);
  }
  QString target_branch = QString::fromStdString(params.get("UpdaterTargetBranch"));
  if (target_branch.isEmpty()) target_branch = QString::fromStdString(params.get("GitBranch"));
  targetBranchBtn->setValue(target_branch);

  // current + new versions
  QString current_version = QString::fromStdString(params.get("UpdaterCurrentDescription"));
  if (current_version.isEmpty()) {
    current_version = QString("%1 (%2)")
      .arg(QString::fromStdString(params.get("Version")), QString::fromStdString(params.get("GitBranch")));
  }
  versionLbl->setText(current_version);
  versionLbl->setDescription(QString::fromStdString(params.get("UpdaterCurrentReleaseNotes")));

  installBtn->setVisible(!is_onroad && params.getBool("UpdateAvailable"));
  installBtn->setValue(QString::fromStdString(params.get("UpdaterNewDescription")));
  installBtn->setDescription(QString::fromStdString(params.get("UpdaterNewReleaseNotes")));

  update();
}
