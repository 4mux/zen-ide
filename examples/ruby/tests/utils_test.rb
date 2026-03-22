# frozen_string_literal: true

require "minitest/autorun"
require_relative "../src/utils"
require_relative "../src/circle"
require_relative "../src/rectangle"

class UtilsTest < Minitest::Test
  def setup
    @shapes = [Circle.new(5), Circle.new(3), Rectangle.new(4, 6)]
  end

  def test_total_area
    expected = Math::PI * 25 + Math::PI * 9 + 24
    assert_in_delta expected, Utils.total_area(@shapes), 1e-9
  end

  def test_largest
    assert_instance_of Circle, Utils.largest(@shapes)
    assert_in_delta Math::PI * 25, Utils.largest(@shapes).area, 1e-9
  end

  def test_filter_by_min_area
    big = Utils.filter_by(@shapes, min_area: 25).to_a
    assert(big.all? { |s| s.area >= 25 })
  end

  def test_filter_by_returns_lazy
    result = Utils.filter_by(@shapes, min_area: 0)
    assert_kind_of Enumerator::Lazy, result
  end

  def test_fibonacci_scales
    radii = Utils.fibonacci_scales(Circle.new(1)).first(7).map(&:radius)
    assert_equal [1, 1, 2, 3, 5, 8, 13].map(&:to_f), radii
  end

  def test_fibonacci_scales_lazy
    result = Utils.fibonacci_scales(Circle.new(1))
    assert_kind_of Enumerator::Lazy, result
  end
end
