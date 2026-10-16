"""Verify the production clock, cached header/light and real footer together."""
import src  # noqa: F401
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget

from ui.footer import build_footer
from ui.themes.contracts import HeaderArea, ThemeHost
from src.tests.support.themes import FooterAppearance
from ui.themes.providers.halloween_effects.animation import HalloweenAnimation, PAUSE_MS, flare_level
from ui.themes.providers.halloween_effects.decorations import MoopForest, _SvgDecoration
from ui.themes.providers.halloween_effects.header import FireHeader

qt = QApplication.instance() or QApplication([])


class HalloweenAnimationTests(unittest.TestCase):
    def setUp(self):
        for item in (patch('ui.footer._read_support_reminder_state', return_value=0.0),
                     patch('ui.footer._update_support_reminder_state', return_value=SimpleNamespace(success=True)),
                     patch.object(QApplication, 'applicationState', return_value=Qt.ApplicationActive)):
            item.start()
            self.addCleanup(item.stop)
        self.window = QWidget()
        layout = QVBoxLayout(self.window)
        self.header = QFrame(self.window)
        self.header.setFixedHeight(90)
        layout.addWidget(self.header)
        self.status = QWidget(self.header)
        self.status.setObjectName('headerStatusCluster')
        self.status.setGeometry(10, 10, 150, 40)
        self.rec = QLabel('REC', self.header)
        self.rec.setGeometry(900, 10, 100, 40)
        layout.addStretch()
        self.app = SimpleNamespace(has_premium_access=lambda: False)
        self.footer = build_footer(self.app)
        layout.addWidget(self.footer)
        self.tree = MoopForest(self.window)
        self.tree.setGeometry(210, 0, 230, 86)
        self.small_tree = _SvgDecoration('forest-right', self.window)
        self.small_tree.setGeometry(690, 0, 180, 86)
        self.clock = HalloweenAnimation(self.window)
        decor = SimpleNamespace(header=self.header, tree=self.tree, small_tree=self.small_tree,
                                host=ThemeHost(self.window, header=HeaderArea(
                                    self.header, lambda: (176, self.rec.x()),
                                    lambda surface: self.status.mapTo(surface, QPoint(self.status.width(), 0)).x() + 8)))
        self.badge = FireHeader(decor, self.clock)
        self.badge.move(440, 20)
        self.provider = FooterAppearance(self.app, self.window, self.clock)
        self.app.footer.set_appearance(self.provider)
        self.link = self.app.footer._support_btn
        self.assertIs(self.link._theme_icon.clock, self.clock)
        self.window.resize(1060, 650)
        self.window.show()
        self.tree.show()
        self.small_tree.show()
        self.badge.show()
        qt.processEvents()
        self.clock.set_enabled(True)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.clock.set_enabled(False)
        for card in (self.app.footer._reminder, self.app.footer._thank_you):
            if card is not None:
                card.dismiss()
        self.app.footer.set_appearance(None)
        self.provider.dispose()
        self.window.close()
        self.window.deleteLater()
        qt.processEvents()

    def test_two_bursts_share_phase_and_reuse_all_rasters(self):
        self.clock.timer.stop()
        for phase in (.25, .6, .9, -1.0, .25):
            self.clock.show_phase(phase)
            self.badge.grab()
            self.link.grab()
            self.assertEqual(self.clock.phase, self.badge.phase)
            self.assertAlmostEqual(self.badge.light.level, flare_level(phase))
        self.assertEqual(self.badge.bank_builds, 1)
        self.assertEqual(self.provider.footer_icon.frames.builds, 1)
        self.assertEqual(self.badge.light.builds, 1)

    def test_face_uses_only_the_two_existing_bursts_and_hides_with_header(self):
        self.clock.timer.stop()
        self.clock.show_phase(-1.0)
        self.assertEqual(self.tree.face_opacity, 0)
        self.clock.show_phase(.25)
        self.assertAlmostEqual(self.tree.face_opacity, .62)
        self.clock.show_phase(.6)
        self.assertEqual(self.tree.face_opacity, 0)
        self.clock.show_phase(.9)
        self.assertGreater(self.tree.face_opacity, 0)
        self.assertLess(self.tree.face_opacity, .62)
        self.badge.hide()
        self.assertEqual(self.tree.face_opacity, 0)
        self.badge.show()
        self.clock.show_phase(.25)
        self.assertAlmostEqual(self.tree.face_opacity, .62)

    def test_face_is_visible_through_gaps_but_never_paints_over_branches(self):
        self.clock.timer.stop()
        self.clock.show_phase(-1.0)
        rest = self.tree.grab().toImage()
        self.clock.show_phase(.25)
        lit = self.tree.grab().toImage()
        branches = self.tree._raster.toImage()
        changed_gaps = 0
        covered_branches = 0
        rect = self.tree.FACE_RECT.toAlignedRect().intersected(self.tree.rect())
        for y in range(rect.top(), rect.bottom() + 1):
            for x in range(rect.left(), rect.right() + 1):
                branch_alpha = branches.pixelColor(x, y).alpha()
                if branch_alpha < 10 and rest.pixel(x, y) != lit.pixel(x, y):
                    changed_gaps += 1
                elif branch_alpha == 255:
                    covered_branches += 1
                    self.assertEqual(rest.pixel(x, y), lit.pixel(x, y))
        self.assertGreater(changed_gaps, 100)
        self.assertGreater(covered_branches, 100)

    def test_timer_sleeps_between_bursts_and_hover_restarts_every_consumer(self):
        self.clock.started -= 2
        self.clock.tick()
        self.assertFalse(self.clock.timer.isActive())
        self.assertTrue(self.clock.wake.isActive())
        self.assertEqual(self.clock.wake.interval(), PAUSE_MS)
        self.assertEqual(self.clock.phase, -1.0)
        self.link.pulse_theme_icon()
        self.assertTrue(self.clock.timer.isActive())
        self.assertFalse(self.clock.wake.isActive())
        self.assertEqual(self.badge.phase, self.clock.phase)
        self.assertEqual(self.clock.phase, 0.0)
        started = self.clock.started
        self.link.resume_heartbeat()
        self.clock.refresh()
        self.assertEqual(self.clock.started, started)

    def test_hidden_header_leaves_footer_running_without_hidden_light(self):
        self.clock.show_phase(.25)
        self.badge.hide()
        self.clock.show_phase(.9)
        self.assertTrue(self.clock.timer.isActive())
        self.assertEqual(self.clock.phase, .9)
        self.assertFalse(self.badge.light.isVisible())
        self.badge.show()
        self.badge.refresh_scene()
        self.assertEqual(self.badge.phase, self.clock.phase)

    def test_background_hidden_and_original_stop_both_timers_and_light(self):
        self.clock.show_phase(.25)
        with patch.object(QApplication, 'applicationState', return_value=Qt.ApplicationInactive):
            self.clock.refresh()
            self.assertFalse(self.clock.timer.isActive())
            self.assertFalse(self.clock.wake.isActive())
            self.assertFalse(self.badge.light.isVisible())
            self.assertEqual(self.clock.phase, -1.0)
        self.clock.refresh()
        self.assertTrue(self.clock.timer.isActive())
        self.window.hide()
        qt.processEvents()
        self.assertFalse(self.clock.timer.isActive())
        self.window.show()
        qt.processEvents()
        self.assertTrue(self.clock.timer.isActive())
        self.clock.set_enabled(False)
        self.app.footer.set_appearance(None)
        self.assertFalse(self.clock.timer.isActive())
        self.assertFalse(self.clock.wake.isActive())
        self.assertFalse(self.badge.light.isVisible())

    def test_support_restarts_shared_phase_and_retains_it_after_dismiss(self):
        self.clock.show_phase(.9)
        card = self.app.footer._reminder
        self.assertTrue(card.play(force=True))
        self.assertEqual(self.clock.phase, 0.0)
        self.assertEqual(self.badge.phase, self.clock.phase)
        self.clock.show_phase(.25)
        card.dismiss()
        self.assertEqual(self.badge.phase, .25)
        self.assertEqual(self.clock.phase, .25)
        self.assertTrue(self.clock.timer.isActive())

    def test_dpi_cache_is_replaced_and_light_stays_inside_header(self):
        self.clock.show_phase(.25)
        self.link.grab()
        cache = self.provider.footer_icon.frames
        cache.frame(2.0, .8, .25)
        self.assertEqual(len(cache.frames), 37)
        self.assertEqual(cache.builds, 2)
        cache.frame(1.0, .8, .9)
        self.assertEqual(len(cache.frames), 37)
        self.assertEqual(cache.builds, 3)
        self.assertLess(self.badge.light.geometry().right(),
                        self.header.mapTo(self.window, self.header.rect().topRight()).x() + 1)

    def test_glow_continues_under_controls_without_tinting_or_blocking_them(self):
        self.rec.move(650, 10)
        self.rec.setStyleSheet('background:#123456;color:white;')
        self.small_tree.hide()
        self.clock.show_phase(.25)
        qt.processEvents()
        self.assertGreater(self.badge.light.geometry().right(),
                           self.rec.mapTo(self.window, self.rec.rect().topLeft()).x())
        point = self.rec.mapTo(self.window, self.rec.rect().bottomLeft())
        point.setX(point.x() + 3)
        point.setY(point.y() - 3)
        shot = self.window.grab().toImage()
        density = shot.devicePixelRatio()
        self.assertEqual(shot.pixelColor(round(point.x()*density), round(point.y()*density)).name(), '#123456')
        center = self.rec.mapTo(self.window, self.rec.rect().center())
        self.assertIs(self.window.childAt(center), self.rec)
        self.assertTrue(self.badge.light.ambient.isVisible())
        self.assertFalse(self.badge.light.ambient.visibleRegion().isEmpty())
        self.clock.set_enabled(False)
        self.assertFalse(self.badge.light.ambient.isVisible())

    def test_uneven_forest_distances_receive_balanced_cached_light(self):
        self.window.resize(1600, 650)
        self.badge.move(650, 20)
        qt.processEvents()
        source = self.badge.mapTo(self.window, QPoint(64, 23))
        self.tree.move(source.x() - 360 - self.tree.width() // 2, 0)
        self.small_tree.move(source.x() + 520 - self.small_tree.width() // 2, 0)
        light = self.badge.light
        for density in (1.0, 2.0):
            with patch.object(light, 'devicePixelRatioF', return_value=density):
                self.badge.prepare()
                image = light.ambient.raster.toImage()
                alphas = []
                for tree in (self.tree, self.small_tree):
                    x = tree.geometry().center().x() - light.x()
                    alphas.append(image.pixelColor(round(x * density),
                                                   round(source.y() * density)).alpha())
                self.assertGreater(min(alphas), 0)
                self.assertLessEqual(abs(alphas[0] - alphas[1]), 1)
                builds = light.builds
                for phase in (.25, .6, .9):
                    self.clock.show_phase(phase)
                self.assertEqual(light.builds, builds)
