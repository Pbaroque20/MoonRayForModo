import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo.progress import Progress


def render(passes, plan=True, wobble=0.0, start=2.0, between=3.0):
    """Play a render of passes (their samples) at 5 s a sample, each with a start-up and a pause before the next, and
    return (time, seconds truly left, seconds shown or None) for each second. wobble makes the pace uneven."""
    now = [0.0]
    state = Progress(clock=lambda: now[0])
    if plan:
        state.plan(passes)
    reports, clock = [], 0.0
    for number, samples in enumerate(passes):
        reports.append((clock, 'begin', number + 1))
        clock += start
        length = 5.0 * samples
        steps = max(4, int(length * 4))
        for step in range(1, steps + 1):
            share = step / steps
            # An uneven pace: fast, then slow, then fast, ending where an even one would.
            share = share + wobble * (0.5 - abs(share - 0.5)) * (1 if (step * 8 // steps) % 2 else -1) * 0.5
            reports.append((clock + length * step / steps, 'report', (number + 1, min(1.0, max(0.0, share)))))
        clock += length + between
    end = clock - between
    rows, index, second = [], 0, 0.0
    while second < end:
        while index < len(reports) and reports[index][0] <= second:
            now[0] = reports[index][0]
            if reports[index][1] == 'begin':
                state.reset_pass()
                state.generation = reports[index][2]
            else:
                state.feed('@@MODO_PROGRESS %d %.4f\n' % reports[index][2])
            index += 1
        now[0] = second
        rows.append((second, end - second, state.remaining(), state.display()[0]))
        second += 1.0
    return rows


class WholeRender(unittest.TestCase):
    def test_three_passes_are_one_countdown(self):
        rows = [row for row in render([1, 4, 16]) if row[2] is not None]
        self.assertGreater(len(rows), 80)
        # It does not start over with each pass: it never climbs by more than a few seconds.
        for before, after in zip(rows, rows[1:]):
            self.assertLess(after[2] - before[2], 4.0, (before, after))
        # Once a third of the render is behind it, it is within a quarter of the truth or ten seconds.
        end = rows[-1][0]
        for moment, truth, shown, _ in rows:
            if moment > end / 3:
                self.assertLess(abs(shown - truth), max(10.0, .25 * truth), (moment, truth, shown))

    def test_the_bar_is_of_the_whole_render(self):
        rows = render([1, 4, 16])
        shown = [percent for _, _, _, percent in rows if percent >= 0]
        self.assertEqual(shown, sorted(shown))
        self.assertLess(shown[len(shown) // 4], 40)

    def test_nothing_wild_as_a_pass_begins(self):
        rows = [row for row in render([1, 4, 16]) if row[2] is not None]
        for moment, truth, shown, _ in rows:
            self.assertLess(shown, 3.0 * truth + 30.0, (moment, truth, shown))

    def test_an_uneven_pace_does_not_swing_it(self):
        rows = [row for row in render([1, 4, 16], wobble=0.6) if row[2] is not None]
        jumps = sorted(abs((b[2] - a[2]) + 1.0) for a, b in zip(rows, rows[1:]))
        self.assertLess(jumps[len(jumps) // 2], 1.5)
        self.assertLess(jumps[-1], 20.0)


class OnePass(unittest.TestCase):
    def test_one_pass_counts_down(self):
        rows = [row for row in render([20], plan=False) if row[2] is not None]
        self.assertGreater(len(rows), 60)
        for moment, truth, shown, _ in rows[5:]:
            self.assertLess(abs(shown - truth), max(6.0, .15 * truth), (moment, truth, shown))

    def test_says_nothing_before_there_is_something_to_go_on(self):
        now = [0.0]
        state = Progress(clock=lambda: now[0])
        state.feed('@@MODO_PROGRESS 1 0.001\n')
        now[0] = 1.0
        state.feed('@@MODO_PROGRESS 1 0.002\n')
        self.assertIsNone(state.remaining())

    def test_reports_of_another_render_are_left_out(self):
        state = Progress(clock=lambda: 0.0)
        state.generation = 7
        state.feed('@@MODO_PROGRESS 6 0.9\n')
        self.assertIsNone(state.percent)
        state.feed('@@MODO_PROGRESS 7 0.25\n')
        self.assertEqual(state.percent, 25.0)

    def test_moonray_s_own_line_is_read(self):
        state = Progress(clock=lambda: 0.0)
        state.feed('GPU utilization = 90%\nRendering [ 10')
        self.assertIsNone(state.percent)
        state.feed('%]\n')
        self.assertEqual(state.percent, 10.0)


class Adaptive(unittest.TestCase):
    def play(self, table, until):
        """An adaptive render whose figure steps through table, (second, share), reported every second as MoonRay
        does. Returns the Progress and what it said each second."""
        now = [0.0]
        state = Progress(clock=lambda: now[0])
        state.plan([16], adaptive=True)
        state.reset_pass()
        said = []
        for second in range(until):
            now[0] = float(second)
            share = [value for moment, value in table if moment <= second]
            if share:
                state.feed('@@MODO_PROGRESS 1 %f\n' % share[-1])
            said.append((second, state.remaining(), state.display()))
        return state, said

    def test_no_time_is_told_from_tiles_that_finish_in_a_rush(self):
        # As MoonRay reported a five-minute adaptive render: next to nothing for most of it, standing still and
        # going back, then a rush.
        state, said = self.play(((5, .0001), (60, .002), (85, .0125), (115, .032), (156, .039), (176, .052), (196, .026),
                                 (226, .25), (236, .115), (246, .31)), 285)
        for second, remaining, shown in said:
            self.assertIsNone(remaining, second)
            self.assertNotIn('left', shown[1])
        self.assertIn('Adaptive sampling: 31% of tiles finished', said[-1][2][1])
        # The bar does not go back when MoonRay's figure does.
        bars = [shown[0] for _, _, shown in said if shown[0] >= 0]
        self.assertEqual(bars, sorted(bars))

    def test_a_time_is_told_while_the_figure_climbs_steadily(self):
        # As MoonRay reported another: a slow start, then half a percent a second to the end.
        table = [(20, .0001)] + [(25 + second, .005 * second) for second in range(1, 186)]
        state, said = self.play(table, 205)
        told = [(second, remaining) for second, remaining, _ in said if remaining is not None]
        self.assertGreater(len(told), 140)
        for second, remaining in told:
            truth = 225 - second
            if second > 80:
                self.assertLess(abs(remaining - truth), max(10.0, .2 * truth), (second, remaining, truth))
            self.assertLess(remaining, 2.5 * truth + 30, (second, remaining, truth))

    def test_moonray_s_rounded_line_is_not_taken_for_a_step_back(self):
        now = [0.0]
        state = Progress(clock=lambda: now[0])
        state.plan([16], adaptive=True)
        state.reset_pass()
        state.feed('@@MODO_PROGRESS 1 0.0227\n')
        now[0] = 1.0
        state.feed('00:00:17    1.6 GB | Rendering [  2%]\n')
        self.assertFalse(state.shaky)
        self.assertAlmostEqual(state.percent, 2.27)


if __name__ == '__main__':
    unittest.main()
