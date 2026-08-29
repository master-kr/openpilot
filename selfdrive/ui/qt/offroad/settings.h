#pragma once

#include <functional>

#include <map>
#include <string>

#include <QButtonGroup>
#include <QFrame>
#include <QLabel>
#include <QPushButton>
#include <QStackedWidget>
#include <QStringList>
#include <QTimer>
#include <QWidget>

#include "selfdrive/ui/ui.h"
#include "selfdrive/ui/qt/util.h"
#include "selfdrive/ui/qt/widgets/controls.h"

// ********** settings window + top-level panels **********
class SettingsWindow : public QFrame {
  Q_OBJECT

public:
  explicit SettingsWindow(QWidget *parent = 0);
  void setCurrentPanel(int index, const QString &param = "");
  bool isCarrotPanelSelected() const;

protected:
  void showEvent(QShowEvent *event) override;

signals:
  void closeSettings();
  void carrotPanelChanged(bool selected);
  void reviewTrainingGuide();
  void showDriverView();
  void expandToggleDescription(const QString &param);

private:
  QPushButton *sidebar_alert_widget;
  QWidget *sidebar_widget;
  QButtonGroup *nav_btns;
  QStackedWidget *panel_widget;
};

class DevicePanel : public ListWidget {
  Q_OBJECT
public:
  explicit DevicePanel(SettingsWindow *parent);

signals:
  void reviewTrainingGuide();
  void showDriverView();

private slots:
  void poweroff();
  void reboot();
  //re_Calibration
  void calibration();
  void updateCalibDescription();

private:
  Params params;
  ButtonControl *pair_device;
};

class TogglesPanel : public ListWidget {
  Q_OBJECT
public:
  explicit TogglesPanel(SettingsWindow *parent);
  void showEvent(QShowEvent *event) override;

public slots:
  void expandToggleDescription(const QString &param);

private slots:
  void updateState(const UIState &s);

private:
  Params params;
  std::map<std::string, ParamControl*> toggles;
  ButtonParamControl *long_personality_setting;

  void updateToggles();
};

class SoftwarePanel : public ListWidget {
  Q_OBJECT
public:
  explicit SoftwarePanel(QWidget* parent = nullptr);

private:
  void showEvent(QShowEvent *event) override;
  void updateLabels();
  void requestUpdate(bool fetch);
  QStringList availableBranches(const QString &remote_output = QString());
  void refreshBranches();
  void showBranchSelection(QStringList branches);

  bool is_onroad = false;

  QLabel *onroadLbl;
  LabelControl *versionLbl;
  ButtonControl *installBtn;
  ButtonControl *downloadBtn;
  ButtonControl *targetBranchBtn;

  Params params;
  ParamWatcher *fs_watch;
};

// Forward declaration
class FirehosePanel;

class CarrotPanel : public QWidget {
  Q_OBJECT

private:
  QStackedLayout* main_layout = nullptr;
  QWidget* homeScreen = nullptr;
  int currentCarrotIndex = 0;

  QWidget* homeWidget;
  QVBoxLayout* carrotLayout;

  ListWidget* cruiseToggles;
  ListWidget* latLongToggles;
  ListWidget* pathToggles;
  ListWidget* dispToggles;
  ListWidget* startToggles;
  ListWidget* speedToggles;

  void togglesCarrot(int widgetIndex);
  void updateButtonStyles();

public:
  explicit CarrotPanel(QWidget* parent = nullptr);
};

class CValueControl : public AbstractControl {
  Q_OBJECT

public:
  using ValueFormatter = std::function<QString(int)>;
  CValueControl(const QString& params, const QString& title, const QString& desc, int min, int max, int unit = 1,
                ValueFormatter formatter = {});

private slots:
  void increaseValue();
  void decreaseValue();

private:
  void showEvent(QShowEvent* event) override;
  void refresh();
  void adjustValue(int delta);

  QPushButton btnplus;
  QPushButton btnminus;
  QLabel label;

  QString m_params;
  int m_min;
  int m_max;
  int m_unit;
  ValueFormatter m_formatter;
};

class MapDataControl : public ButtonControl {
  Q_OBJECT

public:
  explicit MapDataControl(QWidget *parent = nullptr);

protected:
  void showEvent(QShowEvent *event) override;
  void hideEvent(QHideEvent *event) override;

private:
  void requestDownload();
  void refresh();
  bool mapDataPresent() const;

  Params params;
  Params mem_params{"/dev/shm/params"};
  QTimer timer;
};
