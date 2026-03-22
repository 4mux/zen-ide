# frozen_string_literal: true

require "minitest/autorun"
require_relative "../src/vector3"

class Vector3Test < Minitest::Test
  def test_initialize_defaults
    v = Vector3.new
    assert_equal 0.0, v.x
    assert_equal 0.0, v.y
    assert_equal 0.0, v.z
  end

  def test_addition
    a = Vector3.new(1, 2, 3)
    b = Vector3.new(4, 5, 6)
    assert_equal Vector3.new(5, 7, 9), a + b
  end

  def test_subtraction
    a = Vector3.new(5, 7, 9)
    b = Vector3.new(1, 2, 3)
    assert_equal Vector3.new(4, 5, 6), a - b
  end

  def test_scalar_multiplication
    v = Vector3.new(1, 2, 3)
    assert_equal Vector3.new(2, 4, 6), v * 2
  end

  def test_negation
    v = Vector3.new(1, -2, 3)
    assert_equal Vector3.new(-1, 2, -3), -v
  end

  def test_dot_product
    a = Vector3.new(1, 0, 0)
    b = Vector3.new(0, 1, 0)
    assert_equal 0.0, a.dot(b)
  end

  def test_cross_product
    result = Vector3::UNIT_X.cross(Vector3::UNIT_Y)
    assert_equal Vector3::UNIT_Z, result
  end

  def test_length
    v = Vector3.new(3, 4, 0)
    assert_in_delta 5.0, v.length, 1e-9
  end

  def test_normalized
    v = Vector3.new(0, 3, 4)
    n = v.normalized
    assert_in_delta 1.0, n.length, 1e-9
  end

  def test_normalize_zero_raises
    assert_raises(ZeroDivisionError) { Vector3::ZERO.normalized }
  end

  def test_comparable
    short = Vector3.new(1, 0, 0)
    long  = Vector3.new(3, 4, 0)
    assert_operator short, :<, long
  end

  def test_enumerable
    v = Vector3.new(1, 2, 3)
    assert_equal [1.0, 2.0, 3.0], v.to_a
  end

  def test_frozen
    v = Vector3.new(1, 2, 3)
    assert_predicate v, :frozen?
  end

  def test_deconstruct
    v = Vector3.new(1, 2, 3)
    x, y, z = v.deconstruct
    assert_equal [1.0, 2.0, 3.0], [x, y, z]
  end

  def test_deconstruct_keys
    v = Vector3.new(1, 2, 3)
    h = v.deconstruct_keys(nil)
    assert_equal({ x: 1.0, y: 2.0, z: 3.0 }, h)
  end
end
