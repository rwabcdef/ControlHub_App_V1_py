// Candidate 2: the Qt Quick (QML) UI. `hub` is the Python Backend (qt_quick_demo.py).
import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Shapes
import QtCharts

ApplicationWindow {
    id: win
    width: 1280; height: 800
    visible: true
    title: "ControlHub AA26 — Qt Quick (QML) demo"
    color: c.bg
    font.pixelSize: 13

    Material.theme: Material.Dark
    Material.accent: c.primary
    Material.primary: c.primary
    Material.background: c.bg
    Material.containerStyle: Material.Outlined

    QtObject {
        id: c
        readonly property color bg: "#0e1116"
        readonly property color paper: "#161b22"
        readonly property color divider: "#30363d"
        readonly property color text: "#e6edf3"
        readonly property color text2: "#9aa4af"
        readonly property color textDisabled: "#5c6570"
        readonly property color track: "#262c35"
        readonly property color disabledInk: "#4a525c"
        readonly property color warn: "#ffa726"
        readonly property color danger: "#f44336"
        readonly property color success: "#66bb6a"
        readonly property color primary: "#4fc3f7"
        readonly property color rpm: "#4fc3f7"
        readonly property color duty: "#ffb74d"
        readonly property color current: "#e57373"
    }

    // ------------------------------------------------------------ gauge pieces
    // The 200 x 150 view box of Gauge.tsx, scaled to fit (xMidYMid meet).
    // Children work in view units; `view` starts at y = 12 as in the SVG.
    component ViewBox: Item {
        id: vb
        default property alias content: view.data
        property alias view: view
        Item {
            width: 200; height: 150
            anchors.centerIn: parent
            scale: Math.min(vb.width / 200, vb.height / 150)
            Item { id: view; y: -12; width: 200; height: 162 }
        }
    }

    component Scale: Item {
        id: sc
        property real lo: 0
        property real hi: 100
        property int majorTicks: 6
        property real frac: 0
        property color ink: c.rpm
        property real warn: NaN
        property real danger: NaN
        anchors.fill: parent

        function ang(v) { return 150 + Math.max(0, Math.min(1, (v - lo) / (hi - lo))) * 240 }

        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {   // track
                strokeColor: c.track; strokeWidth: 6; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                PathAngleArc { centerX: 100; centerY: 100; radiusX: 86; radiusY: 86; startAngle: 150; sweepAngle: 240 }
            }
            ShapePath {   // value
                strokeColor: sc.ink; strokeWidth: 6; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                PathAngleArc { centerX: 100; centerY: 100; radiusX: 86; radiusY: 86; startAngle: 150
                    sweepAngle: Math.max(0.01, sc.frac * 240) }
            }
            ShapePath {   // warn band
                strokeColor: isNaN(sc.warn) ? "transparent" : c.warn; strokeWidth: 2; fillColor: "transparent"
                PathAngleArc { centerX: 100; centerY: 100; radiusX: 81; radiusY: 81
                    startAngle: isNaN(sc.warn) ? 0 : sc.ang(sc.warn)
                    sweepAngle: isNaN(sc.warn) ? 0 : sc.ang(isNaN(sc.danger) ? sc.hi : sc.danger) - sc.ang(sc.warn) }
            }
            ShapePath {   // danger band
                strokeColor: isNaN(sc.danger) ? "transparent" : c.danger; strokeWidth: 2; fillColor: "transparent"
                PathAngleArc { centerX: 100; centerY: 100; radiusX: 81; radiusY: 81
                    startAngle: isNaN(sc.danger) ? 0 : sc.ang(sc.danger)
                    sweepAngle: isNaN(sc.danger) ? 0 : 390 - sc.ang(sc.danger) }
            }
        }
        // Ticks and labels as items (vector, so they stay sharp when the view box scales)
        Repeater {
            model: sc.majorTicks * 4 + 1
            Item {
                required property int index
                readonly property bool major: index % 4 === 0
                x: 100; y: 100
                rotation: 150 + 240 * index / (sc.majorTicks * 4)
                Rectangle { x: parent.major ? 70 : 75; y: -height / 2; width: parent.major ? 10 : 5
                    height: parent.major ? 1.5 : 0.75; color: c.text2; antialiasing: true }
            }
        }
        Repeater {
            model: sc.majorTicks + 1
            Text {
                required property int index
                readonly property real a: (150 + 240 * index / sc.majorTicks) * Math.PI / 180
                readonly property real v: sc.lo + (sc.hi - sc.lo) * index / sc.majorTicks
                x: 100 + 60 * Math.cos(a) - width / 2; y: 100 + 60 * Math.sin(a) - height / 2
                text: Math.abs(v) >= 1000 ? (+(v / 1000).toFixed(1)) + "k" : "" + (+v.toFixed(2))
                color: c.text2; font.pointSize: 6.4   // 8.5 px; pixelSize only takes ints
            }
        }
    }

    component Needle: Item {
        property real frac: 0
        property color ink: c.rpm
        property real tail: 10
        x: 100; y: 100
        rotation: 150 + frac * 240
        Rectangle { x: -parent.tail; y: -1.25; width: 74 + parent.tail; height: 2.5; radius: 1.25; color: parent.ink; antialiasing: true }
        Rectangle { x: -5; y: -5; width: 10; height: 10; radius: 5; color: c.paper; border.color: parent.ink; border.width: 2
            rotation: -parent.rotation }
    }

    component Readout: Item {
        property string value: "—"
        property string label: ""
        property color color: c.text
        Text { x: 40; y: 117; width: 120; horizontalAlignment: Text.AlignHCenter; text: parent.value
            color: parent.color; font.pixelSize: 22; font.weight: Font.DemiBold }
        Text { x: 40; y: 140; width: 120; horizontalAlignment: Text.AlignHCenter; text: parent.label
            color: c.text2; font.pixelSize: 9 }
    }

    // Gauge.tsx: the readout refreshes at 10 Hz, the needle every frame
    component Gauge: ViewBox {
        id: gauge
        property real value: 0
        property real lo: 0
        property real hi: 100
        property int decimals: 0
        property int majorTicks: 6
        property color ink: c.rpm
        property real warn: NaN
        property real danger: NaN
        property string label: ""
        property string shown: "—"
        readonly property real frac: Math.max(0, Math.min(1, (value - lo) / (hi - lo)))
        Timer { interval: 100; running: true; repeat: true; onTriggered: gauge.shown = gauge.value.toFixed(gauge.decimals) }
        Scale { lo: gauge.lo; hi: gauge.hi; majorTicks: gauge.majorTicks; frac: gauge.frac; ink: gauge.ink
            warn: gauge.warn; danger: gauge.danger }
        Needle { frac: gauge.frac; ink: gauge.ink }
        Readout { value: gauge.shown; label: gauge.label; anchors.fill: parent }
    }

    // SpeedDial.tsx. mode: "edit", "readonly" (a meter: full colour, inert) or "disabled"
    component SpeedDial: ViewBox {
        id: dial
        property int value: 0
        property int lo: 0
        property int hi: 300
        property string mode: "edit"
        property color color: c.rpm
        signal moved(int v)
        readonly property color ink: mode === "disabled" ? c.disabledInk : color
        readonly property real frac: Math.max(0, Math.min(1, (value - lo) / (hi - lo)))
        readonly property bool live: mode === "edit"
        activeFocusOnTab: live

        function set(v) {
            const nv = Math.round(Math.max(lo, Math.min(hi, v)))
            if (nv !== value) { value = nv; moved(nv) }
        }
        function step(d) {
            if ((value > hi && d > 0) || (value < lo && d < 0)) return
            set(value + d)
        }
        function rel(x, y) {
            const deg = Math.atan2(y - 100, x - 100) * 180 / Math.PI
            return (((deg - 150) % 360) + 360) % 360
        }
        function valueOf(r) {
            const t = r <= 240 ? r / 240 : (r - 240 < 360 - r ? 1 : 0)
            return lo + t * (hi - lo)
        }

        Scale { lo: dial.lo; hi: dial.hi; frac: dial.frac; ink: dial.ink }
        Needle { frac: dial.frac; ink: dial.ink; tail: 0 }
        Rectangle {   // knob
            readonly property real a: (150 + dial.frac * 240) * Math.PI / 180
            x: 100 + 86 * Math.cos(a) - 7; y: 100 + 86 * Math.sin(a) - 7
            width: 14; height: 14; radius: 7; color: c.paper; border.color: dial.ink; border.width: 2.5
        }
        Readout { anchors.fill: parent; value: "" + dial.value; label: "Target (RPM)"
            color: dial.mode === "disabled" ? c.textDisabled : c.text }
        Rectangle { x: 8; y: 8; width: 184; height: 184; radius: 92; color: "transparent"
            border.color: c.primary; border.width: 0.8; visible: dial.activeFocus; opacity: 0.6 }

        MouseArea {
            anchors.fill: parent
            enabled: dial.live
            cursorShape: dial.live ? Qt.PointingHandCursor : Qt.ArrowCursor
            property bool dragging: false
            onPressed: (m) => {
                dial.forceActiveFocus()
                const r = dial.rel(m.x, m.y)
                if (Math.hypot(m.x - 100, m.y - 100) < 50 || r > 240) { m.accepted = false; return }
                dragging = true
                dial.set(dial.valueOf(r))
            }
            onPositionChanged: (m) => { if (dragging) dial.set(dial.valueOf(dial.rel(m.x, m.y))) }
            onReleased: dragging = false
            onWheel: (w) => { if (w.angleDelta.y !== 0) dial.step(w.angleDelta.y > 0 ? 1 : -1) }
        }
        Keys.enabled: live
        Keys.onPressed: (e) => {
            const d = ({ [Qt.Key_Up]: 1, [Qt.Key_Right]: 1, [Qt.Key_Down]: -1, [Qt.Key_Left]: -1,
                         [Qt.Key_PageUp]: 10, [Qt.Key_PageDown]: -10 })[e.key]
            if (d !== undefined) dial.step(d)
            else if (e.key === Qt.Key_Home) dial.set(lo)
            else if (e.key === Qt.Key_End) dial.set(hi)
            else return
            e.accepted = true
        }
    }

    // ------------------------------------------------------------ chrome
    component Panel: Rectangle {
        id: pnl
        property string title: ""
        property alias action: actionSlot.data
        default property alias content: body.data
        color: c.paper; radius: 6; border.color: c.divider
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 12; spacing: 8
            RowLayout {
                visible: pnl.title !== "" || actionSlot.children.length > 0
                Label { text: pnl.title; color: c.text2; font.weight: Font.DemiBold; Layout.fillWidth: true }
                Item { id: actionSlot; implicitWidth: childrenRect.width; implicitHeight: childrenRect.height }
            }
            Item { id: body; Layout.fillWidth: true; Layout.fillHeight: true }
        }
    }

    component Chip: Rectangle {
        property string text
        property string role: "default"
        readonly property color tone: role === "success" ? c.success : role === "info" ? "#29b6f6" : c.divider
        implicitWidth: chipLabel.implicitWidth + 18; implicitHeight: 22; radius: 11
        color: role === "default" ? "transparent" : tone; border.color: tone
        Label { id: chipLabel; anchors.centerIn: parent; text: parent.text; font.pixelSize: 12
            color: parent.role === "default" ? c.text2 : "#0b1a12" }
    }

    // MUI-style: a spinner replaces the label while its command is in flight;
    // the tooltip says why it's disabled (a parent HoverHandler, as a disabled button gets no hover).
    component CmdButton: Item {
        id: cb
        property string label
        property string glyph
        property string which
        property string reason: ""
        signal run()
        Layout.fillWidth: true
        implicitHeight: btn.implicitHeight
        Button {
            id: btn
            anchors.fill: parent
            highlighted: true
            Material.roundedScale: Material.ExtraSmallScale
            text: hub.busy === cb.which ? "" : cb.glyph + "  " + cb.label
            enabled: cb.reason === "" && (hub.busy === "" || hub.busy === cb.which)
            onClicked: cb.run()
            BusyIndicator { anchors.centerIn: parent; width: 26; height: 26; running: hub.busy === cb.which; visible: running }
        }
        HoverHandler { id: hov }
        ToolTip.visible: hov.hovered && cb.reason !== ""
        ToolTip.text: cb.reason
        ToolTip.delay: 300
    }

    component Caption: Label { color: c.text2; font.pixelSize: 11; horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true }
    component Overline: Label { color: c.text2; font.pixelSize: 11; font.letterSpacing: 1 }
    component Divider: Rectangle { Layout.fillWidth: true; height: 1; color: c.divider }

    component StripChart: Panel {
        id: sc
        property string field
        property string label
        property color ink
        property real yMin: 0
        property real yMax: 1
        property string yFormat: "%.0f"
        ColumnLayout {
            anchors.fill: parent; spacing: 2
            RowLayout {
                Rectangle { width: 12; height: 3; radius: 1; color: sc.ink }
                Caption { text: sc.label; horizontalAlignment: Text.AlignLeft }
                Caption { text: "t (s)"; horizontalAlignment: Text.AlignRight; color: c.textDisabled }
            }
            // QtCharts, not QtGraphs: QtGraphs' GraphsView crashes on load with PySide6 6.12
            // / Python 3.14 (any RHI backend). QtCharts is deprecated but works.
            ChartView {
                Layout.fillWidth: true; Layout.fillHeight: true
                margins { left: 0; right: 4; top: 0; bottom: 0 }
                backgroundColor: c.paper; plotAreaColor: c.paper
                legend.visible: false; antialiasing: true
                ValueAxis { id: ax; objectName: sc.field + "X"; min: 0; max: 10; tickType: ValueAxis.TicksDynamic
                    tickInterval: 1; tickAnchor: 0; labelFormat: "%.0f"
                    gridLineColor: "#232a33"; lineVisible: false; labelsColor: c.text2; labelsFont.pixelSize: 11 }
                ValueAxis { id: ay; objectName: sc.field + "Y"; min: sc.yMin; max: sc.yMax; tickCount: 5
                    labelFormat: sc.yFormat; gridLineColor: "#232a33"; lineVisible: false; labelsColor: c.text2
                    labelsFont.pixelSize: 11 }
                LineSeries { id: line; axisX: ax; axisY: ay; color: sc.ink; width: 1.5 }   // not useOpenGL: it draws nothing under Qt 6's RHI
                Component.onCompleted: hub.registerChart(sc.field, line, ax, ay)
            }
        }
    }

    // ------------------------------------------------------------ the screen
    header: ToolBar {
        Material.background: c.bg
        height: 46
        RowLayout {
            anchors.fill: parent; anchors.leftMargin: 12; anchors.rightMargin: 12; spacing: 10
            Label { text: "<b>ControlHub</b> <font color='#9aa4af'>AA26</font>"; textFormat: Text.RichText; font.pixelSize: 16 }
            Item { Layout.fillWidth: true }
            Label { text: "Sim:"; color: c.text2 }
            ComboBox { model: hub.scenarios; currentIndex: hub.scenarioIndex; implicitWidth: 200; implicitHeight: 36
                topInset: 0; bottomInset: 0; onActivated: (i) => hub.setScenario(i) }
            Button { text: "Remote button 1"; flat: true; onClicked: hub.remoteButton()
                ToolTip.visible: hovered; ToolTip.text: "Start / stop a run as the remote hub would" }
            Label { text: hub.fpsText; color: c.text2; Layout.preferredWidth: 120 }
            Chip { text: "SIM · connected"; role: "success" }
        }
        Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: c.divider }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0
        TabBar {
            Layout.fillWidth: true
            Material.background: c.bg
            Repeater { model: ["Dashboard", "Config", "MQTT log", "Files", "Dev"]
                TabButton { text: modelData; width: implicitWidth + 16 } }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: c.divider }

        RowLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; Layout.margins: 12; spacing: 12

            // ---- DashboardControl.tsx
            Panel {
                title: "Control"
                action: Chip { text: hub.chipText; role: hub.chipRole }
                Layout.preferredWidth: 230; Layout.fillHeight: true
                ColumnLayout {
                    anchors.fill: parent; spacing: 8
                    Overline { text: "CONTROL" }
                    ComboBox {
                        Layout.fillWidth: true; implicitHeight: 40
                        model: ["Forward", "Reverse"]
                        currentIndex: hub.direction === "reverse" ? 1 : 0
                        enabled: hub.startBlocked === "" && hub.busy === ""
                        onActivated: (i) => hub.setDirection(i ? "reverse" : "forward")
                    }
                    CmdButton { label: "Start"; glyph: "▶"; which: "start"; reason: hub.startBlocked; onRun: hub.start() }
                    Item {
                        Layout.fillWidth: true; Layout.preferredHeight: 140
                        SpeedDial {
                            id: dial
                            anchors.fill: parent
                            hi: hub.dialMax; mode: hub.dialState
                            // A Binding element, not a plain binding: it survives the dial's own set()
                            Binding on value { value: hub.dialValue }
                            onMoved: (v) => hub.setRpm(v)
                        }
                        HoverHandler { id: dialHover }
                        ToolTip.visible: dialHover.hovered && hub.dialTip !== ""
                        ToolTip.text: hub.dialTip
                    }
                    Divider {}
                    Overline { text: "LIFT" }
                    ComboBox {
                        id: moveMode
                        Layout.fillWidth: true; implicitHeight: 40
                        model: ["Up/Down", "For/Rev"]
                        onActivated: (i) => hub.setMoveMode(i ? "forRev" : "upDown")
                    }
                    RowLayout {
                        visible: moveMode.currentIndex === 0; spacing: 8
                        CmdButton { label: "Up"; glyph: "↑"; which: "up"; reason: hub.liftBlocked; onRun: hub.liftUp() }
                        CmdButton { label: "Down"; glyph: "↓"; which: "down"; reason: hub.liftBlocked; onRun: hub.liftDown() }
                    }
                    ComboBox {
                        visible: moveMode.currentIndex === 1
                        Layout.fillWidth: true; implicitHeight: 40
                        model: ["Forward", "Reverse"]
                        onActivated: (i) => hub.setLiftDirection(i ? "reverse" : "forward")
                    }
                    CmdButton { visible: moveMode.currentIndex === 1; label: "Start"; glyph: "▶"; which: "move"
                        reason: hub.liftBlocked; onRun: hub.liftMove() }
                    Caption { text: hub.liftCaption }
                    Rectangle {   // Done lamp
                        Layout.fillWidth: true; height: 32; radius: 6; color: "transparent"
                        border.color: hub.done ? c.success : c.divider
                        Behavior on border.color { ColorAnimation { duration: 200 } }
                        Row {
                            anchors.centerIn: parent; spacing: 8
                            Rectangle { width: 12; height: 12; radius: 6; anchors.verticalCenter: parent.verticalCenter
                                color: hub.done ? c.success : "#3a4049"
                                layer.enabled: hub.done
                                Rectangle { anchors.centerIn: parent; width: 20; height: 20; radius: 10; z: -1
                                    color: c.success; opacity: hub.done ? 0.25 : 0 } }
                            Label { text: "Done"; font.weight: Font.DemiBold; color: hub.done ? c.success : c.textDisabled }
                        }
                    }
                    Caption { text: hub.liftProgress; visible: text !== "" }
                    Divider {}
                    CmdButton { label: "Stop"; glyph: "■"; which: "stop"; onRun: hub.stop() }
                    Item { Layout.fillHeight: true }
                }
            }

            // ---- DashboardPage.tsx
            ColumnLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; spacing: 12
                RowLayout {
                    Layout.fillWidth: true; Layout.fillHeight: false
                    Layout.preferredHeight: 210; Layout.maximumHeight: 210; spacing: 12
                    Panel { title: "Speed"; Layout.fillWidth: true; Layout.fillHeight: true
                        Gauge { anchors.fill: parent; value: hub.rpm; hi: hub.rpmMax; ink: c.rpm; label: "Speed (RPM)"
                            warn: hub.rpmMax * 0.8; danger: hub.rpmMax * 0.93 } }
                    Panel { title: "PWM duty cycle"; Layout.fillWidth: true; Layout.fillHeight: true
                        Gauge { anchors.fill: parent; value: hub.duty; hi: 100; decimals: 1; majorTicks: 5; ink: c.duty
                            label: "Duty (%)" } }
                    Panel { title: "Current"; Layout.fillWidth: true; Layout.fillHeight: true
                        Gauge { anchors.fill: parent; value: hub.current; hi: hub.currentMax; decimals: 2; majorTicks: 5
                            ink: c.current; label: "Current (A)"; warn: hub.currentMax * 0.7; danger: hub.currentMax * 0.9 } }
                }
                GridLayout {
                    Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 300
                    columns: 2; rowSpacing: 12; columnSpacing: 12
                    StripChart { field: "rpm"; label: "Speed (RPM)"; ink: c.rpm; yMax: 300
                        Layout.columnSpan: 2; Layout.fillWidth: true; Layout.fillHeight: true }
                    StripChart { field: "duty"; label: "PWM duty (%)"; ink: c.duty; yMax: 100
                        Layout.fillWidth: true; Layout.fillHeight: true }
                    StripChart { field: "current"; label: "Current (A)"; ink: c.current; yMax: 2; yFormat: "%.1f"
                        Layout.fillWidth: true; Layout.fillHeight: true }
                }
            }
        }
    }
}
