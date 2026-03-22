# frozen_string_literal: true

require "minitest/autorun"
require_relative "../src/circle"

class CircleTest < Minitest::Test
  def test_area
    c = Circle.new(5)
    assert_in_delta Math::PI * 25, c.area, 1e-9
  end

  def test_perimeter
    c = Circle.new(3)
    assert_in_delta 2 * Math::PI * 3, c.perimeter, 1e-9
  end

  def test_scale
    c = Circle.new(2).scale(3)
    assert_in_delta 6.0, c.radius, 1e-9
  end

  def test_comparable
    small = Circle.new(1)
    large = Circle.new(5)
    assert_operator small, :<, large
  end

  def test_position_default
    c = Circle.new(1)
    assert_equal Vector3::ZERO, c.position
  end

  def test_position_custom
    pos = Vector3.new(1, 2, 0)
    c = Circle.new(1, position: pos)
    assert_equal pos, c.position
  end

  def test_translate
    c = Circle.new(3)
    moved = c.translate(Vector3.new(5, 0, 0))
    assert_equal Vector3.new(5, 0, 0), moved.position
    assert_in_delta c.area, moved.area, 1e-9
  end

  def test_registry
    assert_equal Circle, Shape.registry[:circle]
  end

  def test_to_s
    c = Circle.new(2.5)
    assert_match(/Circle/, c.to_s)
  end
end
