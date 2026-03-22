#include "vector3.h"

// Template instantiations so the linker finds them
namespace geo {
template class Vector3<float>;
template class Vector3<double>;
template class Vector3<int>;
} // namespace geo
