# frozen_string_literal: true

require "minitest/autorun"
require_relative "../src/renderer"
require_relative "../src/circle"
require_relative "../src/rectangle"

class RendererTest < Minitest::Test
  def setup
    @renderer = Renderer.new
    @renderer << Circle.new(5) << Rectangle.new(4, 6)
  end

  def test_enumerable
    assert_equal 2, @renderer.count
  end

  def test_stats_count
    assert_equal 2, @renderer.stats.count
  end

  def test_stats_total_area
    expected = Math::PI * 25 + 24
    assert_in_delta expected, @renderer.stats.total_area, 1e-9
  end

  def test_stats_largest
    assert_instance_of Circle, @renderer.stats.largest
  end

  def test_render_output
    output = capture_io { @renderer.render }.first
    assert_match(/Scene: 2 shapes/, output)
    assert_match(/Total area/, output)
  end

  def test_chaining
    r = Renderer.new
    result = r << Circle.new(1)
    assert_same r, result
  end
end
