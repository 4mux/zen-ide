# frozen_string_literal: true

require "minitest/autorun"
require_relative "../src/rectangle"

class RectangleTest < Minitest::Test
  def test_area
    r = Rectangle.new(4, 6)
    assert_in_delta 24.0, r.area, 1e-9
  end

  def test_perimeter
    r = Rectangle.new(4, 6)
    assert_in_delta 20.0, r.perimeter, 1e-9
  end

  def test_square_true
    r = Rectangle.new(5, 5)
    assert_predicate r, :square?
  end

  def test_square_false
    r = Rectangle.new(4, 6)
    refute_predicate r, :square?
  end

  def test_diagonal
    r = Rectangle.new(3, 4)
    assert_in_delta 5.0, r.diagonal, 1e-9
  end

  def test_scale
    r = Rectangle.new(2, 3).scale(2)
    assert_in_delta 4.0, r.width, 1e-9
    assert_in_delta 6.0, r.height, 1e-9
  end

  def test_translate
    r = Rectangle.new(4, 6)
    moved = r.translate(Vector3.new(0, 10, 0))
    assert_equal Vector3.new(0, 10, 0), moved.position
    assert_in_delta r.area, moved.area, 1e-9
  end

  def test_deconstruct_keys
    r = Rectangle.new(4, 6)
    h = r.deconstruct_keys(nil)
    assert_equal 4.0, h[:width]
    assert_equal 6.0, h[:height]
  end

  def test_registry
    assert_equal Rectangle, Shape.registry[:rectangle]
  end

  def test_to_s
    r = Rectangle.new(4, 6)
    assert_match(/Rectangle/, r.to_s)
  end
end
